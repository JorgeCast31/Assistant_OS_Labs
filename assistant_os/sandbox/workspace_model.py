"""
WorkspaceModel — three-directory workspace layout for sandbox executions.

Layout
------
workspace/
    input/   ← code files written here; container's working directory
    output/  ← container may write structured output here (optional scratch)
    out/     ← governed artifact export root; only files here are collected

Rules
-----
- The container's only writable mount is the workspace root.
- Artifacts must be written to /workspace/out/ to be collected by ArtifactPolicy.
- workspace/input/ is the container's --workdir.
- cleanup() removes the three sub-dirs but NOT the workspace root itself.
- out/ is the governed export root; output/ is unmanaged scratch space.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class WorkspaceModel:
    """
    Manages the three-directory workspace layout for a single execution.

    Parameters
    ----------
    workspace_path : str — absolute path to an existing directory on the host.

    Usage
    -----
        ws = WorkspaceModel("/tmp/my_workspace")
        ws.prepare()
        ws.write_code("print('hello')")
        # ... run execution ...
        artifacts = ws.list_artifacts()
        ws.cleanup()
    """

    def __init__(self, workspace_path: str) -> None:
        self.root = Path(workspace_path).resolve()
        self.input_dir = self.root / "input"
        self.output_dir = self.root / "output"
        self.out_dir = self.root / "out"

    def prepare(self) -> None:
        """Create input / output / out sub-directories.

        Permissions are set explicitly (not umask-derived) so that the
        container process (UID 65534 / nobody) can access the workspace
        regardless of the host's umask or how the caller created the
        workspace root (e.g. pytest tmp_path uses 0o700 on Linux).

        Contract:
          workspace root : 0o755  — traversable by container UID
          input/         : 0o755  — readable + traversable; container does not write here
          output/        : 0o777  — container may write scratch data
          out/           : 0o777  — container writes governed artifact files here
        """
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Apply explicit permissions after creation so umask cannot restrict access.
        self.root.chmod(0o755)
        self.input_dir.chmod(0o755)
        self.output_dir.chmod(0o777)
        self.out_dir.chmod(0o777)

    def write_code(self, code: str, filename: str = "main.py") -> Path:
        """
        Write code to workspace/input/<filename>.

        Parameters
        ----------
        code     : Python source to write.
        filename : Bare filename (no path separators allowed).

        Returns
        -------
        Path — absolute path to the written file.

        Raises
        ------
        ValueError if filename contains "/" or "\\".
        """
        if "/" in filename or "\\" in filename:
            raise ValueError(
                f"entry_point must be a bare filename, not a path: {filename!r}"
            )
        target = self.input_dir / filename
        target.write_text(code, encoding="utf-8")
        # Explicit read permission for container UID 65534 (nobody), independent of umask.
        target.chmod(0o644)
        return target

    def list_artifacts(self) -> list[str]:
        """
        Return relative paths (from workspace root) of all files in out/.

        Returns an empty list if out/ does not exist or is empty.
        """
        if not self.out_dir.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in self.out_dir.rglob("*")
            if p.is_file()
        )

    def cleanup(self) -> None:
        """
        Remove input / output / out directories.

        Does NOT remove the workspace root itself.
        Safe to call even if sub-directories do not exist (no-op).
        """
        for sub in (self.input_dir, self.output_dir, self.out_dir):
            if sub.exists():
                shutil.rmtree(sub, ignore_errors=True)
