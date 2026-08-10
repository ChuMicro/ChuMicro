"""Workspace path resolution and project-tree classification.

:class:`WorkspaceLayout` resolves the paths under a workspace
root (``workspace.yml``, ``secrets.toml``, ``devices.yml``,
``projects/``, ``shared/``, ``libraries/``, ``packages/``).
:meth:`WorkspaceLayout.from_dir` walks up from a starting
directory until it finds a ``workspace.yml``, so users can
invoke commands from anywhere inside the tree.

Workspace layout::

    <root>/
        workspace.yml          # gitignored defaults + credentials
        devices.yml            # board entries (chumicro_deploy.config.default)
        projects/<...>/<name>/ # one directory per project, optionally nested
        shared/                # shared library code
        packages/              # third-party packages (gitignored)

Directories under ``projects/`` may nest arbitrarily deep
(``projects/upstairs/bedroom_sensor/``,
``projects/garage/sensors/door_open/``).  Each is walked and
classified:

* **project**: leaf containing an entry-point file (``app.py`` /
  ``code.py`` / ``main.py``).  Deployable.
* **namespace**: recursively contains at least one project or
  another namespace.  Pure organizational structure, not deployed
  itself.
* **supporting**: neither.  Silently ignored, so ``docs/`` and
  design notes can live anywhere in the tree without flagging.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: Filename whose presence anchors a workspace root.
WORKSPACE_MARKER: str = "workspace.yml"

#: Default subdirectory that contains one directory per project.
PROJECTS_DIRNAME: str = "projects"

#: Filenames that mark a directory as a deployable "project".  Any
#: single one is enough.  ``app.py`` is the
#: workspace convention (the workspace boot shim looks for it).
#: ``code.py`` / ``main.py`` are accepted so users with bare
#: CircuitPython / MicroPython entry-points still see their project
#: classified.
ENTRY_POINT_FILENAMES: tuple[str, ...] = ("app.py", "code.py", "main.py")


class ProjectClassification(StrEnum):
    """How a directory under ``projects/`` is treated by the workspace tools."""

    #: Deployable: has an entry-point file.
    PROJECT = "project"
    #: Recursively contains at least one project or namespace.
    NAMESPACE = "namespace"
    #: Neither.  Silently ignored by deploy / list / new.
    SUPPORTING = "supporting"


class WorkspaceNotFoundError(FileNotFoundError):
    """Raised when no ``workspace.yml`` is found above the start directory."""


def _is_skipped_dirname(name: str) -> bool:
    """True for directory names that are never descended into.

    Leading ``.`` covers VCS / hidden dirs; leading ``_`` covers
    workspace-tooling-reserved directories such as ``_template`` and
    ``_generated``.
    """
    return name.startswith((".", "_"))


def _has_entry_point(path: Path) -> bool:
    """True when *path* contains any of :data:`ENTRY_POINT_FILENAMES`."""
    return any((path / name).is_file() for name in ENTRY_POINT_FILENAMES)


def _walk_classified(
    parent: Path,
    prefix: tuple[str, ...],
    out: list[tuple[str, ProjectClassification]],
) -> bool:
    """DFS-walk *parent*, append every classified child to *out*.

    *prefix* is the slash-form path of *parent* (empty tuple at the
    projects-dir root).  Children classified as ``PROJECT`` are appended
    immediately; children classified as ``NAMESPACE`` are appended
    after their subtree is walked so a top-down sort puts the
    namespace before its descendants.

    Returns ``True`` when *parent* contained at least one project or
    namespace child.  The caller uses this to decide whether *parent*
    itself qualifies as a namespace.
    """
    has_project_or_namespace = False
    for child in parent.iterdir():
        if not child.is_dir() or _is_skipped_dirname(child.name):
            continue
        child_prefix = (*prefix, child.name)
        slash_path = "/".join(child_prefix)
        if _has_entry_point(child):
            out.append((slash_path, ProjectClassification.PROJECT))
            has_project_or_namespace = True
            continue
        marker = len(out)
        if _walk_classified(child, child_prefix, out):
            # Insert the namespace entry at the marker so it sorts
            # before its descendants in the result.
            out.insert(marker, (slash_path, ProjectClassification.NAMESPACE))
            has_project_or_namespace = True
    return has_project_or_namespace


def runner_invocation(workspace_root: Path) -> str:
    """Return the command prefix a hint should name for this workspace.

    A workspace driven by the template's ``run.py`` shim keeps its
    venv off PATH, so a hint naming ``chumicro-workspace ...`` fails
    with command-not-found when pasted; a standalone install has no
    ``run.py`` and drives the CLI directly.  Picks whichever
    invocation actually resolves: ``python3 run.py`` when the shim
    exists at *workspace_root*, ``chumicro-workspace`` otherwise.
    """
    if (workspace_root / "run.py").is_file():
        return "python3 run.py"
    return "chumicro-workspace"


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
        """Path to ``<root>/workspace.yml``."""
        return self.root / WORKSPACE_MARKER

    @property
    def secrets_toml(self) -> Path:
        """Path to ``<root>/secrets.toml`` (gitignored device-bound config).

        Materialized on first ``setup`` from the shipped template
        (:func:`read_secrets_toml_template`).  Carries wifi credentials,
        MQTT broker auth, and any other workspace-wide default that
        flows onto a board through ``runtime_config.msgpack``.
        May not exist on a fresh workspace before ``setup`` runs.
        """
        return self.root / "secrets.toml"

    @property
    def devices_yaml(self) -> Path:
        """Path to ``<root>/devices.yml``.  May not exist on a fresh workspace."""
        return self.root / "devices.yml"

    @property
    def projects_dir(self) -> Path:
        """Path to ``<root>/projects/``."""
        return self.root / PROJECTS_DIRNAME

    @property
    def shared_dir(self) -> Path:
        """Path to ``<root>/shared/`` for flat shared modules.

        A file ``shared/foo.py`` is imported by projects under its bare
        module name (``from foo import bar``), never ``shared.foo``: the
        deploy search path roots at this directory, so its modules resolve
        as top-level names without any package scaffolding.  No tests, no
        version, no chumicro library shape.
        """
        return self.root / "shared"

    @property
    def libraries_dir(self) -> Path:
        """Path to ``<root>/libraries/`` for full chumicro-style library trees.

        Each entry is a proper chumicro library package with
        ``src/<name>/``, ``tests/``, optional ``docs/`` and ``examples/``,
        ``pyproject.toml``, ``VERSION``.  Created by
        ``chumicro-workspace new --library``.  Use this when the library
        is meant to be publishable.

        ``import_graph.build_search_paths`` includes
        ``libraries/<name>/src/`` for every entry so projects can ``import
        my_lib`` without a separate :data:`library_sources` mapping.
        """
        return self.root / "libraries"

    @property
    def packages_dir(self) -> Path:
        """Path to ``<root>/packages/`` (third-party packages, gitignored)."""
        return self.root / "packages"

    def project_dir(self, name: str) -> Path:
        """Return the directory for the named project (existence not checked).

        *name* may be a single segment (``"bedroom_sensor"``), slash-form
        (``"upstairs/bedroom_sensor"``), or dotted (``"upstairs.bedroom_sensor"``).
        Dotted forms are normalized to slash so the ``Path`` join lands
        in the right directory.
        """
        normalized = name.replace(".", "/")
        return self.projects_dir / normalized

    def list_projects(self) -> list[str]:
        """Return slash-form paths for every project under ``projects/``, sorted.

        Walks the tree recursively per the classifier in
        :data:`ProjectClassification`.  Each path returned is a deployable
        leaf.  Namespaces, supporting directories, ``_template`` /
        ``_generated`` and hidden dirs are filtered out.

        Returns an empty list when ``projects/`` doesn't exist yet.
        """
        if not self.projects_dir.is_dir():
            return []
        collected: list[tuple[str, ProjectClassification]] = []
        _walk_classified(self.projects_dir, (), collected)
        return sorted(
            slash_path
            for slash_path, classification in collected
            if classification is ProjectClassification.PROJECT
        )

    def iter_projects_with_classification(
        self,
    ) -> list[tuple[str, ProjectClassification]]:
        """Return every classified directory under ``projects/``, sorted.

        Includes both projects and namespaces.  Namespaces are needed so
        the tree renderer can draw branches above leaves and callers that
        report on supporting branches.  Sorting is by slash-form path,
        which gives natural depth-first display order.
        """
        if not self.projects_dir.is_dir():
            return []
        collected: list[tuple[str, ProjectClassification]] = []
        _walk_classified(self.projects_dir, (), collected)
        return sorted(collected)

    @classmethod
    def from_dir(cls, start: Path | None = None) -> WorkspaceLayout:
        """Walk up from *start* until a ``workspace.yml`` is found.

        The walk lets users run ``python3 run.py deploy ...`` from any
        directory inside the workspace.  The root is resolved as the
        nearest ancestor with a ``workspace.yml``.

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
