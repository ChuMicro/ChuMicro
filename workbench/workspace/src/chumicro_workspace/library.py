"""Fetch curated chumicro libraries from a snapshot channel and
place them under the workspace's ``libraries/<name>/``.

:func:`fetch_library` pulls one package; :func:`fetch_closure`
pulls a root plus every chumicro library it transitively imports.
Both place each library where the deploy walker treats it like
any local checkout, and both raise :class:`LibraryFetchError`
with a :class:`LibraryFetchFailureKind` value on every failure
so callers can coach instead of dumping a traceback.

Placement preserves user work.  An existing tree is moved to
``_library-backups/<name>/<old-version>-<timestamp>/`` before a
re-fetch, and a tree carrying the ``.chumicro-local`` sentinel
is left untouched entirely.

The snapshot transport (HTTP, tarball, index parsing) lives in
:mod:`chumicro_workspace.library_channel`.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from chumicro_workspace.dep_resolver import (
    chumicro_dependencies,
    transitive_closure,
)

#: Trees a curated copy carries.  ``src/`` is what the deploy walker
#: needs.  ``tests/``, ``examples/``, and ``docs/`` make the copy
#: self-contained so a user can run and adapt the library without
#: leaving the workspace.
REQUIRED_TREES = ("src", "tests", "examples", "docs")

#: Top-level files copied alongside the trees.
COPIED_FILES = ("pyproject.toml", "VERSION", "README.md")

#: Workspace-relative dir holding pre-upgrade backups of edited trees.
LIBRARY_BACKUPS_DIRNAME = "_library-backups"

#: File the user drops into ``libraries/<name>/`` to claim the tree as
#: their own.  ``library add`` / ``update`` / ``switch-channel`` then
#: leave it untouched, even when a transitive walk would otherwise
#: re-fetch it.  Dot-prefixed for parity with the deploy scope filter
#: (skipped by both transports' on-device listings).  Delete the file
#: to resume tracking the channel.
LOCAL_EDIT_SENTINEL = ".chumicro-local"

#: Sentinel recorded in ``workspace.yml`` for ``--floating`` entries.
#: Means "track the channel's latest snapshot" rather than a pinned tag.
HEAD = "HEAD"


def is_locally_held(workspace_root: Path, package: str) -> bool:
    """Whether ``libraries/<package>/`` carries the user-edit sentinel."""
    return (
        workspace_root / "libraries" / package / LOCAL_EDIT_SENTINEL
    ).is_file()


class LibraryFetchFailureKind(Enum):
    """Closed set of fetch-failure kinds — no string-typed failures."""

    NETWORK = "network"
    PACKAGE_NOT_FOUND = "package-not-found"
    BAD_ARCHIVE = "bad-archive"
    MALFORMED_PACKAGE = "malformed-package"
    INDEX_MALFORMED = "index-malformed"
    UNKNOWN_CHANNEL = "unknown-channel"


class LibraryFetchError(RuntimeError):
    """A fetch failed.  ``kind`` is the machine-readable category."""

    def __init__(self, kind: LibraryFetchFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def read_installed_version(workspace_root: Path, package: str) -> str | None:
    """Return the VERSION of a curated library on disk, or None if absent."""
    version_file = workspace_root / "libraries" / package / "VERSION"
    if not version_file.is_file():
        return None
    return version_file.read_text(encoding="utf-8").strip() or None


def remove_library(workspace_root: Path, package: str) -> bool:
    """Delete a curated library's tree.  Returns True if it existed."""
    target = workspace_root / "libraries" / package
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def _validate_curated_content(root: Path, package: str) -> None:
    """Confirm an extracted library tree carries everything needed."""
    missing = [tree for tree in REQUIRED_TREES if not (root / tree).is_dir()]
    missing += [name for name in COPIED_FILES if not (root / name).is_file()]
    if missing:
        raise LibraryFetchError(
            LibraryFetchFailureKind.MALFORMED_PACKAGE,
            f"snapshot tree for {package!r} is missing "
            f"{', '.join(sorted(missing))}",
        )


def _backup_existing(destination: Path, workspace_root: Path) -> Path | None:
    """Move an existing curated tree aside before it is replaced.

    Returns the backup directory, or ``None`` if there was nothing to
    back up.  The backup is keyed by the version that was on disk so a
    user can tell which edits came from where.
    """
    if not destination.exists():
        return None
    old_version = read_installed_version(
        workspace_root, destination.name,
    ) or "unknown"
    backup_dir = (
        workspace_root
        / LIBRARY_BACKUPS_DIRNAME
        / destination.name
        / f"{old_version}-{int(time.time())}"
    )
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.move(str(destination), str(backup_dir))
    return backup_dir


def _place_library(
    source_root: Path, package: str, workspace_root: Path,
) -> Path:
    """Install an extracted tree, respecting the local-edit sentinel.

    Validates the tree, then:

    * If the destination carries ``.chumicro-local``
      (:data:`LOCAL_EDIT_SENTINEL`), leave it alone and return the
      existing path — the user has claimed the tree as their own and
      doesn't want it replaced, even on a transitive re-fetch.  Prints
      a one-line notice so the user knows the channel had a different
      version available.
    * Otherwise, back up an existing curated copy, then copy the
      curated subset into ``libraries/<package>/``.

    Returns the destination either way.
    """
    _validate_curated_content(source_root, package)
    destination = workspace_root / "libraries" / package
    if is_locally_held(workspace_root, package):
        channel_version = (source_root / "VERSION").read_text(
            encoding="utf-8",
        ).strip()
        installed_version = read_installed_version(
            workspace_root, package,
        ) or "unknown"
        print(
            f"library: kept local edits in libraries/{package}/ "
            f"({LOCAL_EDIT_SENTINEL} sentinel present; on-disk "
            f"v{installed_version}, channel has v{channel_version}).",
        )
        return destination
    _backup_existing(destination, workspace_root)
    destination.mkdir(parents=True)
    for tree in REQUIRED_TREES:
        shutil.copytree(source_root / tree, destination / tree)
    for name in COPIED_FILES:
        shutil.copy2(source_root / name, destination / name)
    return destination


def _snapshot_and_tarball(channel: str, version: str, http_get):
    """Resolve the channel snapshot and fetch its tarball once.

    *version* is the :data:`HEAD` sentinel (latest snapshot) or a
    pinned snapshot tag.
    """
    # Deferred so importing this module is cheap and test fixtures can
    # swap the transport without pulling in placement logic.
    from chumicro_workspace.library_channel import (
        fetch_snapshot_tarball,
        resolve_snapshot,
    )

    snapshot = resolve_snapshot(
        channel,
        tag=None if version == HEAD else version,
        http_get=http_get,
    )
    return snapshot, fetch_snapshot_tarball(
        channel, snapshot, http_get=http_get,
    )


def _real_http_get(url: str) -> bytes:
    """Default transport, deferred so importing this module is cheap."""
    from chumicro_workspace.library_channel import _real_http_get as backend

    return backend(url)


def fetch_library(
    package: str,
    *,
    channel: str = "stable",
    version: str = HEAD,
    workspace_root: Path,
    http_get: Callable[[str], bytes] = _real_http_get,
) -> Path:
    """Fetch one *package* from a channel snapshot into the workspace.

    *version* is :data:`HEAD` (the channel's latest snapshot) or a
    pinned snapshot tag.  An existing curated copy is backed up, not
    clobbered.  Returns the destination directory; raises
    :class:`LibraryFetchError` with a classified kind on any failure.
    """
    snapshot, tarball = _snapshot_and_tarball(channel, version, http_get)
    from chumicro_workspace.library_channel import extract_library

    with tempfile.TemporaryDirectory(prefix="chumicro-library-") as staging:
        root = extract_library(tarball, package, Path(staging))
        return _place_library(root, package, workspace_root)


def fetch_closure(
    root: str,
    *,
    channel: str = "stable",
    version: str = HEAD,
    workspace_root: Path,
    http_get: Callable[[str], bytes] = _real_http_get,
) -> list[str]:
    """Fetch *root* and every chumicro library reachable from it.

    One ``index.json`` GET plus one tarball GET cover the whole
    closure.  See :mod:`chumicro_workspace.library_channel` for why.
    Breadth-first from *root* over each placed library's
    ``chumicro-`` deps, via the shared
    :func:`~chumicro_workspace.dep_resolver.transitive_closure`.
    Returns the closure as import names in BFS order (root first),
    cycle-safe.  Raises :class:`LibraryFetchError` from the first
    member that fails to extract.  Already-placed members stay on
    disk and the caller decides whether to roll back.
    """
    snapshot, tarball = _snapshot_and_tarball(channel, version, http_get)
    from chumicro_workspace.library_channel import extract_library

    def deps_of(name: str) -> list[str]:
        with tempfile.TemporaryDirectory(
            prefix="chumicro-library-",
        ) as staging:
            extracted = extract_library(tarball, name, Path(staging))
            _place_library(extracted, name, workspace_root)
        return chumicro_dependencies(
            workspace_root / "libraries" / name / "pyproject.toml",
        )

    return transitive_closure([root], deps_of)
