from __future__ import annotations

from pathlib import Path


AUDIT_MEMORY_DIR = Path("assistant_os") / "memory"
DEFAULT_POLICE_AUDIT_PATH = AUDIT_MEMORY_DIR / "police_audit.jsonl"
DEFAULT_CANDIDATE_AUDIT_PATH = AUDIT_MEMORY_DIR / "candidate_audit.jsonl"


def police_audit_path(base_dir: Path | str = AUDIT_MEMORY_DIR) -> Path:
    return Path(base_dir) / "police_audit.jsonl"


def candidate_audit_path(base_dir: Path | str = AUDIT_MEMORY_DIR) -> Path:
    return Path(base_dir) / "candidate_audit.jsonl"
