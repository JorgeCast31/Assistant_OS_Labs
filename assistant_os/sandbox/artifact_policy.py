"""
ArtifactPolicy — governed persistence layer for sandbox executions.

Design
------
Artifacts are files produced by container executions that AssistantOS may
persist or surface to callers.  They are strictly separated from execution
metadata (always-persisted system records) and from the execution I/O streams.

Export root
-----------
Only files written to /workspace/out/ inside the container are collectable.
Files written anywhere else in the workspace are NOT collected.

Policy invariants
-----------------
  1. Only files under workspace/out/ are candidates.
  2. Each file must not exceed MAX_ARTIFACT_SIZE_BYTES.
  3. Classification must be in ALLOWED_CLASSIFICATIONS.
  4. BLOCKED_CLASSIFICATIONS are rejected unconditionally.
  5. ArtifactManifest records SHA-256 hash and byte size for each accepted file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Hard cap per artifact file (1 MB).
MAX_ARTIFACT_SIZE_BYTES: int = 1_048_576

# Allowed artifact classifications (v0: all collected files default to "output").
ALLOWED_CLASSIFICATIONS: frozenset[str] = frozenset({"output", "log", "data"})

# Always-blocked regardless of policy or caller intent.
BLOCKED_CLASSIFICATIONS: frozenset[str] = frozenset({"secret", "credential"})

# The only sub-directory of workspace that may export artifacts.
EXPORT_ROOT_NAME: str = "out"


@dataclass
class ArtifactRecord:
    """
    Metadata record for a single collected artifact.

    Fields
    ------
    path           : Relative path from workspace root (e.g. "out/result.json").
    size_bytes     : File size in bytes at collection time.
    sha256         : Hex-encoded SHA-256 digest of the file contents.
    classification : Semantic category (must be in ALLOWED_CLASSIFICATIONS).
    """

    path: str
    size_bytes: int
    sha256: str
    classification: str


@dataclass
class ArtifactManifest:
    """
    Collection of accepted artifact records for one execution.

    Fields
    ------
    records     : Accepted artifacts (post-policy).
    rejected    : Rejected artifact paths with reasons (for audit).
    export_root : Relative name of the export root within workspace ("out").
    """

    records: list[ArtifactRecord] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    export_root: str = EXPORT_ROOT_NAME

    def to_dict(self) -> dict:
        return {
            "export_root": self.export_root,
            "records": [
                {
                    "path": r.path,
                    "size_bytes": r.size_bytes,
                    "sha256": r.sha256,
                    "classification": r.classification,
                }
                for r in self.records
            ],
            "rejected": list(self.rejected),
        }


class ArtifactPolicy:
    """
    Applies the artifact collection policy to a workspace.

    Usage
    -----
        policy = ArtifactPolicy()
        manifest = policy.collect(workspace_path="/abs/path/to/workspace")
    """

    def __init__(
        self,
        max_size_bytes: int = MAX_ARTIFACT_SIZE_BYTES,
        allowed_classifications: Optional[frozenset] = None,
    ) -> None:
        self._max_size = max_size_bytes
        self._allowed = allowed_classifications or ALLOWED_CLASSIFICATIONS

    def collect(self, workspace_path: str) -> ArtifactManifest:
        """
        Collect artifacts from workspace/out/.

        Only files under workspace/out/ are candidates.  Classification
        defaults to "output" for all v0 collected files.

        Returns an ArtifactManifest with accepted records and rejected entries.
        """
        ws = Path(workspace_path).resolve()
        out_dir = ws / EXPORT_ROOT_NAME
        manifest = ArtifactManifest()

        if not out_dir.exists() or not out_dir.is_dir():
            return manifest

        for candidate in sorted(out_dir.rglob("*")):
            if not candidate.is_file():
                continue

            rel_path = str(candidate.relative_to(ws))

            # Guard: must be strictly under out/ (rglob should guarantee this,
            # but defend against symlinks pointing outside).
            try:
                candidate.resolve().relative_to(out_dir.resolve())
            except ValueError:
                manifest.rejected.append({
                    "path": rel_path,
                    "reason": "outside export root (symlink escape rejected)",
                })
                continue

            # Guard: size cap
            size = candidate.stat().st_size
            if size > self._max_size:
                manifest.rejected.append({
                    "path": rel_path,
                    "reason": f"exceeds max size ({size} > {self._max_size})",
                })
                continue

            # v0: default classification for all collected files
            classification = "output"

            # Guard: blocked classification (defense-in-depth for future overrides)
            if classification in BLOCKED_CLASSIFICATIONS:
                manifest.rejected.append({
                    "path": rel_path,
                    "reason": f"blocked classification: {classification!r}",
                })
                continue

            # Guard: unknown classification
            if classification not in self._allowed:
                manifest.rejected.append({
                    "path": rel_path,
                    "reason": f"unknown classification: {classification!r}",
                })
                continue

            sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
            manifest.records.append(ArtifactRecord(
                path=rel_path,
                size_bytes=size,
                sha256=sha256,
                classification=classification,
            ))

        return manifest
