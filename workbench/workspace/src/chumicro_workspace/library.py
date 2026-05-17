"""PyPI fetch backend for curated workspace libraries.

Pull a chumicro library's sdist from PyPI into the user's workspace
``libraries/<package>/`` so the deploy walker treats it like a local
library — same import-graph rules, same opt-out mechanism, same
FAT-safe deploy path.  This module owns only the fetch primitive; the
``chumicro-workspace library`` CLI surface and its coaching loop are
built on top of it separately.

Channel -> PyPI distribution (mirrors the experimental rename the
release pipeline already performs):

    stable        chumicro-<lib>
    experimental  chumicro-<lib>-experimental

The ``version: HEAD`` sentinel means "track the channel's latest" — it
maps to an unpinned ``pip download`` because PyPI has no "HEAD"
version, and the release pipeline publishes every VERSION-bumped main
merge to the experimental package, so the channel's latest already is
main's latest.

Failures are classified into a closed set so a caller can coach the
user instead of dumping a pip traceback.  The per-kind user-facing
recovery prose + retry loop live with the CLI; this module's contract
is the typed :class:`LibraryFetchError` carrying a
:class:`LibraryFetchFailureKind`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from chumicro_workspace.dep_resolver import chumicro_dependencies

#: Trees the curated copy must carry.  ``src/`` is what the deploy
#: walker needs; ``tests/``/``examples/``/``docs/`` make the curated
#: library self-contained (the sdist now ships them for this reason).
REQUIRED_TREES = ("src", "tests", "examples", "docs")

#: Top-level files copied alongside the trees.
COPIED_FILES = ("pyproject.toml", "VERSION", "README.md")

#: Sentinel recorded in ``workspace.yml`` for ``--floating`` entries.
HEAD = "HEAD"


class LibraryFetchFailureKind(Enum):
    """Closed set of fetch-failure kinds — no string-typed failures."""

    NETWORK = "network"
    PACKAGE_NOT_FOUND = "package-not-found"
    NO_SDIST = "no-sdist"
    BAD_ARCHIVE = "bad-archive"
    MALFORMED_PACKAGE = "malformed-package"
    UNKNOWN = "unknown"


class LibraryFetchError(RuntimeError):
    """A fetch failed.  ``kind`` is the machine-readable category."""

    def __init__(self, kind: LibraryFetchFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def channel_distribution(package: str, channel: str) -> str:
    """Map an import name + channel to its PyPI distribution name.

    ``("chumicro_mqtt", "stable")`` -> ``"chumicro-mqtt"``;
    ``("chumicro_mqtt", "experimental")`` -> ``"chumicro-mqtt-experimental"``.
    """
    base = package.replace("_", "-")
    if channel == "stable":
        return base
    if channel == "experimental":
        return f"{base}-experimental"
    raise LibraryFetchError(
        LibraryFetchFailureKind.UNKNOWN,
        f"unknown channel {channel!r} (expected 'stable' or 'experimental')",
    )


def classify_pip_failure(stderr: str) -> LibraryFetchFailureKind:
    """Map ``pip download`` stderr to a failure kind.

    Pattern-matches on the substrings pip emits; falls open to
    :attr:`LibraryFetchFailureKind.UNKNOWN`.
    """
    lowered = stderr.lower()
    if "could not find a version" in lowered or "no matching distribution" in lowered:
        return LibraryFetchFailureKind.PACKAGE_NOT_FOUND
    network_markers = (
        "temporary failure in name resolution",
        "failed to establish a new connection",
        "connection refused",
        "network is unreachable",
        "timed out",
        "retries exceeded",
    )
    if any(marker in lowered for marker in network_markers):
        return LibraryFetchFailureKind.NETWORK
    return LibraryFetchFailureKind.UNKNOWN


def _safe_extract(sdist: Path, into: Path) -> Path:
    """Extract *sdist* under *into*; return the unpacked root directory.

    Rejects members with absolute paths or ``..`` traversal before
    extracting — ``tarfile``'s ``data`` filter would do this, but it
    only exists on Python 3.12+ and this package supports 3.11.
    """
    try:
        with tarfile.open(sdist, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                target = (into / member.name).resolve()
                if not str(target).startswith(str(into.resolve())):
                    raise LibraryFetchError(
                        LibraryFetchFailureKind.BAD_ARCHIVE,
                        f"sdist member escapes extraction dir: {member.name!r}",
                    )
            archive.extractall(into)  # noqa: S202 — members validated above
    except tarfile.TarError as error:
        raise LibraryFetchError(
            LibraryFetchFailureKind.BAD_ARCHIVE,
            f"could not unpack sdist {sdist.name}: {error}",
        ) from error

    roots = [child for child in into.iterdir() if child.is_dir()]
    if len(roots) != 1:
        raise LibraryFetchError(
            LibraryFetchFailureKind.MALFORMED_PACKAGE,
            f"expected one top-level dir in {sdist.name}, found {len(roots)}",
        )
    return roots[0]


def fetch_library(
    package: str,
    *,
    channel: str = "stable",
    version: str = HEAD,
    workspace_root: Path,
    subprocess_runner=subprocess.run,
) -> Path:
    """Fetch *package* from PyPI into ``workspace_root/libraries/<package>/``.

    Runs ``pip download --no-deps --no-binary :all:`` so the sdist
    (not a wheel) lands, unpacks it, and copies ``src/`` + ``tests/`` +
    ``examples/`` + ``docs/`` + the top-level metadata files into the
    workspace.  An existing curated copy is replaced.

    *version* may be a PyPI-resolvable string or the :data:`HEAD`
    sentinel (unpinned — the channel's latest).  *subprocess_runner*
    is injected so tests can fake the pip call.

    Returns the destination directory.  Raises
    :class:`LibraryFetchError` with a classified kind on any failure.
    """
    distribution = channel_distribution(package, channel)
    spec = distribution if version == HEAD else f"{distribution}=={version}"

    with tempfile.TemporaryDirectory(prefix="chumicro-library-") as staging:
        staging_dir = Path(staging)
        command = [
            sys.executable, "-m", "pip", "download",
            "--no-deps", "--no-binary", ":all:",
            spec, "-d", str(staging_dir),
        ]
        completed = subprocess_runner(  # noqa: S603 — args fully controlled
            command, capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr or ""
            raise LibraryFetchError(
                classify_pip_failure(stderr),
                f"pip download failed for {spec!r}:\n{stderr.strip()}",
            )

        tarballs = sorted(staging_dir.glob("*.tar.gz"))
        if not tarballs:
            raise LibraryFetchError(
                LibraryFetchFailureKind.NO_SDIST,
                f"no sdist (.tar.gz) downloaded for {spec!r} — "
                "is the published distribution wheel-only?",
            )

        unpacked_root = _safe_extract(tarballs[0], staging_dir / "unpacked")
        _validate_curated_content(unpacked_root, spec)

        destination = workspace_root / "libraries" / package
        _replace_tree(unpacked_root, destination)
        return destination


def _validate_curated_content(root: Path, spec: str) -> None:
    """Confirm an unpacked sdist carries everything a curated copy needs."""
    missing = [tree for tree in REQUIRED_TREES if not (root / tree).is_dir()]
    missing += [name for name in COPIED_FILES if not (root / name).is_file()]
    if missing:
        raise LibraryFetchError(
            LibraryFetchFailureKind.MALFORMED_PACKAGE,
            f"sdist for {spec!r} is missing {', '.join(sorted(missing))} — "
            "it predates the curated-content sdist change",
        )


def _replace_tree(source_root: Path, destination: Path) -> None:
    """Copy curated content from *source_root* into a fresh *destination*."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for tree in REQUIRED_TREES:
        shutil.copytree(source_root / tree, destination / tree)
    for name in COPIED_FILES:
        shutil.copy2(source_root / name, destination / name)


def remove_library(workspace_root: Path, package: str) -> bool:
    """Delete a curated library's tree.  Returns True if it existed."""
    target = workspace_root / "libraries" / package
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


def read_installed_version(workspace_root: Path, package: str) -> str | None:
    """Return the VERSION of a curated library on disk, or None if absent."""
    version_file = workspace_root / "libraries" / package / "VERSION"
    if not version_file.is_file():
        return None
    return version_file.read_text(encoding="utf-8").strip() or None


def fetch_closure(
    root: str,
    *,
    channel: str = "stable",
    version: str = HEAD,
    workspace_root: Path,
    subprocess_runner: Callable[..., subprocess.CompletedProcess] = (
        subprocess.run
    ),
) -> list[str]:
    """Fetch *root* and every chumicro library it transitively needs.

    Breadth-first from *root*: fetch a library, read its
    ``[project].dependencies`` for chumicro entries, enqueue the
    unseen ones.  *root* is fetched at the requested *version*; each
    transitive dependency tracks its channel's latest (an unpinned
    fetch) — channel does not leak, version pins are per-library.

    Returns the closure as import names in BFS order (root first).
    Cycle-safe.  Raises :class:`LibraryFetchError` from the first
    fetch that fails (the partially-fetched libraries stay on disk;
    the caller decides whether to roll back).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    queue: list[str] = [root]
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
        fetch_library(
            name,
            channel=channel,
            version=version if name == root else HEAD,
            workspace_root=workspace_root,
            subprocess_runner=subprocess_runner,
        )
        pyproject = workspace_root / "libraries" / name / "pyproject.toml"
        for dependency in chumicro_dependencies(pyproject):
            if dependency not in seen:
                queue.append(dependency)
    return ordered
