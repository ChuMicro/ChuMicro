"""Workspace path resolution + thing-tree classification.

Locates the canonical files of a project workspace (workspace.yml,
devices.yml, secrets.yml, ``things/<...>/``) given a starting
directory.  The CLI walks up from the current working directory
until it finds a ``workspace.yml`` so users can invoke commands from
anywhere inside the workspace tree (typical Git / monorepo
ergonomics).

Things may be nested arbitrarily deep under ``things/`` —
``things/upstairs/bedroom_sensor/``, ``things/garage/sensors/door_open/``,
and so on (Phase 1 of ``plans/workstreams/workspace-ecosystem.md``).
A directory is classified by walking its contents:

* **thing** — leaf containing an entry-point file
  (``app.py`` / ``code.py`` / ``main.py``).  Deployable.
* **namespace** — recursively contains at least one thing (or another
  namespace).  Pure organisational structure; not deployed itself.
* **supporting** — neither.  Silently ignored — lets users park
  ``docs/``, design notes, etc. anywhere in the tree without flagging
  them.

The layout is documented in ``plans/workstreams/project-workspace.md``
and reified by the canonical template at
``ChuMicro/ChuMicro-Workspace-Template`` (Decision 0038)::

    <root>/
        workspace.yml          # workspace defaults (Decision 0035)
        devices.yml            # board entries (chumicro_deploy.config.default)
        secrets.yml            # gitignored, optional
        things/<...>/<name>/   # one directory per "thing", optionally nested
        libs/                  # shared library code
        packages/              # third-party packages (gitignored)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: Filename whose presence anchors a workspace root.
WORKSPACE_MARKER: str = "workspace.yml"

#: Default subdirectory that contains one directory per thing.
THINGS_DIRNAME: str = "things"

#: Filenames that mark a directory as a deployable "thing".  Order is
#: irrelevant — any single one is enough.  ``app.py`` is the
#: workspace-runtime convention (Decision 0029); ``code.py`` /
#: ``main.py`` are accepted so users with bare CircuitPython /
#: MicroPython entry-points still see their thing classified.
ENTRY_POINT_FILENAMES: tuple[str, ...] = ("app.py", "code.py", "main.py")


class ThingClassification(StrEnum):
    """How a directory under ``things/`` is treated by the workspace tools."""

    #: Deployable — has an entry-point file.
    THING = "thing"
    #: Recursively contains at least one thing or namespace.
    NAMESPACE = "namespace"
    #: Neither — silently ignored by deploy / list / new.
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
    out: list[tuple[str, ThingClassification]],
) -> bool:
    """DFS-walk *parent*, append every classified child to *out*.

    *prefix* is the slash-form path of *parent* (empty tuple at the
    things-dir root).  Children classified as ``THING`` are appended
    immediately; children classified as ``NAMESPACE`` are appended
    after their subtree is walked so a top-down sort puts the
    namespace before its descendants.

    Returns ``True`` when *parent* contained at least one thing or
    namespace child — caller uses this to decide whether *parent*
    itself qualifies as a namespace.
    """
    has_thing_or_namespace = False
    for child in parent.iterdir():
        if not child.is_dir() or _is_skipped_dirname(child.name):
            continue
        child_prefix = (*prefix, child.name)
        slash_path = "/".join(child_prefix)
        if _has_entry_point(child):
            out.append((slash_path, ThingClassification.THING))
            has_thing_or_namespace = True
            continue
        # Not a thing — see if its subtree contains one.  Recurse first
        # (collects descendants), then decide whether to label *child*
        # itself as a namespace.
        marker = len(out)
        if _walk_classified(child, child_prefix, out):
            # Insert the namespace entry at the marker so namespaces
            # come before their descendants in the result.
            out.insert(marker, (slash_path, ThingClassification.NAMESPACE))
            has_thing_or_namespace = True
    return has_thing_or_namespace


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
        """Path to ``<root>/libs/`` — small shared modules dropped flat.

        The lighter-weight cousin of :attr:`libraries_dir`.  Files under
        ``libs/`` are imported by things directly (``from libs.foo import
        bar``) without any package scaffolding.  Use this for "I wrote a
        50-line helper my things need to share" — no tests, no version,
        no chumicro library shape.  See :attr:`libraries_dir` for the
        full-package alternative.
        """
        return self.root / "libs"

    @property
    def libraries_dir(self) -> Path:
        """Path to ``<root>/libraries/`` — full chumicro-style library trees.

        The heavier-weight cousin of :attr:`libs_dir`.  Each entry is a
        proper chumicro library package — ``src/<name>/``, ``tests/``,
        optional ``docs/`` and ``examples/``, ``pyproject.toml``,
        ``VERSION``.  Created by ``chumicro-workspace new --library``.
        Use this when you intend to publish (or later might) — you get
        the same scaffolding the chumicro mono-repo uses.

        ``import_graph.build_search_paths`` includes
        ``libraries/<name>/src/`` for every entry so things can ``import
        my_lib`` without a separate :data:`library_sources` mapping.
        """
        return self.root / "libraries"

    @property
    def packages_dir(self) -> Path:
        """Path to ``<root>/packages/`` — third-party packages (gitignored)."""
        return self.root / "packages"

    def thing_dir(self, name: str) -> Path:
        """Return the directory for the named thing (existence not checked).

        *name* may be a single segment (``"bedroom_sensor"``), slash-form
        (``"upstairs/bedroom_sensor"``), or dotted (``"upstairs.bedroom_sensor"``)
        — dotted forms are normalised to slash so the ``Path`` join lands
        in the right directory.
        """
        normalised = name.replace(".", "/")
        return self.things_dir / normalised

    def list_things(self) -> list[str]:
        """Return slash-form paths for every thing under ``things/``, sorted.

        Walks the tree recursively per the classifier in
        :data:`ThingClassification`.  Each path returned is a deployable
        leaf — namespaces, supporting directories, ``_template`` /
        ``_generated`` and hidden dirs are filtered out.

        Returns an empty list when ``things/`` doesn't exist yet.
        """
        if not self.things_dir.is_dir():
            return []
        collected: list[tuple[str, ThingClassification]] = []
        _walk_classified(self.things_dir, (), collected)
        return sorted(
            slash_path
            for slash_path, classification in collected
            if classification is ThingClassification.THING
        )

    def iter_things_with_classification(
        self,
    ) -> list[tuple[str, ThingClassification]]:
        """Return every classified directory under ``things/``, sorted.

        Includes both things and namespaces — namespaces are needed so
        the tree renderer can draw branches above leaves and ``doctor``
        can report on empty / supporting branches.  Sorting is by
        slash-form path, which gives natural depth-first display order.
        """
        if not self.things_dir.is_dir():
            return []
        collected: list[tuple[str, ThingClassification]] = []
        _walk_classified(self.things_dir, (), collected)
        return sorted(collected)

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
