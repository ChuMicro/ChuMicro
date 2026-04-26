"""Workspace path resolution.

Locates the canonical files of a project workspace (workspace.yml,
devices.yml, secrets.yml, ``things/<name>/``) given a starting
directory.  The CLI walks up from the current working directory
until it finds a ``workspace.yml`` so users can invoke commands from
anywhere inside the workspace tree (typical Git / monorepo
ergonomics).

The layout is documented in ``plans/workstreams/project-workspace.md``
and reified by the canonical template at
``ChuMicro/ChuMicro-Workspace-Template`` (Decision 0038)::

    <root>/
        workspace.yml          # workspace defaults (Decision 0035)
        devices.yml            # board entries (chumicro_deploy.config.default)
        secrets.yml            # gitignored, optional
        things/<name>/         # one directory per "thing" (a deployable program)
        libs/                  # shared library code
        packages/              # third-party packages (gitignored)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Filename whose presence anchors a workspace root.
WORKSPACE_MARKER: str = "workspace.yml"

#: Default subdirectory that contains one directory per thing.
THINGS_DIRNAME: str = "things"


class WorkspaceNotFoundError(FileNotFoundError):
    """Raised when no ``workspace.yml`` is found above the start directory."""


@dataclass(frozen=True)
class WorkspaceLayout:
    """Resolved paths for a single project workspace.

    Construct with :meth:`from_dir` (walks up from a starting
    directory) or by passing *root* directly when the location is
    already known.

    Attributes:
        root: Directory containing ``workspace.yml``.  Every other
            path is derived from this.
    """

    root: Path

    @property
    def workspace_yaml(self) -> Path:
        """Path to ``<root>/workspace.yml`` (always exists by construction)."""
        return self.root / WORKSPACE_MARKER

    @property
    def devices_yaml(self) -> Path:
        """Path to ``<root>/devices.yml``.  May not exist on a fresh workspace."""
        return self.root / "devices.yml"

    @property
    def secrets_yaml(self) -> Path:
        """Path to ``<root>/secrets.yml``.  Optional and gitignored."""
        return self.root / "secrets.yml"

    @property
    def things_dir(self) -> Path:
        """Path to ``<root>/things/`` — the parent of every thing directory."""
        return self.root / THINGS_DIRNAME

    @property
    def libs_dir(self) -> Path:
        """Path to ``<root>/libs/`` — shared library source for thing imports."""
        return self.root / "libs"

    @property
    def packages_dir(self) -> Path:
        """Path to ``<root>/packages/`` — third-party packages (gitignored)."""
        return self.root / "packages"

    def thing_dir(self, name: str) -> Path:
        """Return the directory for the named thing (existence not checked)."""
        return self.things_dir / name

    def list_things(self) -> list[str]:
        """Return the names of every thing under ``things/``, sorted.

        Skips the special ``_template`` directory (used by the ``new``
        command as a copy-source) and entries whose names start with
        ``.`` (hidden) or ``_`` (workspace-tooling-reserved).  Returns
        an empty list when ``things/`` doesn't exist yet.
        """
        if not self.things_dir.is_dir():
            return []
        names: list[str] = []
        for entry in self.things_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name.startswith((".", "_")):
                continue
            names.append(entry.name)
        return sorted(names)

    @classmethod
    def from_dir(cls, start: Path | None = None) -> WorkspaceLayout:
        """Walk up from *start* until a ``workspace.yml`` is found.

        Mirrors the way ``git`` discovers its repository root — users
        can run ``python run.py deploy ...`` from any directory inside
        the workspace and the right files get located.

        Args:
            start: Starting directory.  Defaults to ``Path.cwd()``.

        Raises:
            WorkspaceNotFoundError: When no ``workspace.yml`` exists
                in *start* or any of its parents.
        """
        starting_dir = (start if start is not None else Path.cwd()).resolve()
        for candidate in [starting_dir, *starting_dir.parents]:
            if (candidate / WORKSPACE_MARKER).is_file():
                return cls(root=candidate)
        raise WorkspaceNotFoundError(
            f"no {WORKSPACE_MARKER} found in {starting_dir} or any parent",
        )
