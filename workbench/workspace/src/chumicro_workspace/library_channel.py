"""Snapshot-channel download backend for curated workspace libraries.

A curated library reaches the workspace by being read out of a
published *snapshot channel*.  A channel is a tag on a full-source-tree
repo, and the state at that tag is an internally-consistent set every
library was built together in.  A tag is the whole set, so pinning is
to a snapshot, not a per-library version.  Library pyprojects carry no
version constraints, so the closure a library declares in its
``pyproject.toml`` is whatever shipped in the same snapshot.

Two channels, one repo each::

    stable        ChuMicro/ChuMicro-Libraries
    experimental  ChuMicro/ChuMicro-Libraries-Experimental

Each repo carries one ``<name>/`` directory per library (the same
``src/ tests/ examples/ docs/`` + metadata shape it has upstream) and a
root ``index.json`` that doubles as the per-snapshot manifest and the
browse catalog: every library's version, one-line description, and
README path as of that tag.  ``index.json`` on the default branch
records the latest tag, so resolving "latest" is one GET, not a
releases-API call.

Every network touch is a single injected ``http_get(url) -> bytes``,
so the whole backend runs against a local fixture with no sockets.
Failures raise the shared :class:`~chumicro_workspace.library.
LibraryFetchError` with a closed-set kind.
"""

from __future__ import annotations

import io
import json
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from chumicro_workspace.library import (
    LibraryFetchError,
    LibraryFetchFailureKind,
)

#: Maps each channel to its source-tree repo.  The ``-Experimental``
#: suffix is on the repo, not on the package name, so switching channel
#: switches repo while imports stay the same.
CHANNEL_REPOS = {
    "stable": "ChuMicro/ChuMicro-Libraries",
    "experimental": "ChuMicro/ChuMicro-Libraries-Experimental",
}

_DEFAULT_TIMEOUT_SECONDS = 30


def _real_http_get(url: str) -> bytes:
    """GET *url*, returning the body bytes."""
    try:
        with urllib.request.urlopen(  # noqa: S310 — https GitHub URLs only
            url, timeout=_DEFAULT_TIMEOUT_SECONDS,
        ) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        status_code = error.code
        # HTTPError is a readable response, so close it to keep its
        # spooled body from leaking.
        error.close()
        kind = (
            LibraryFetchFailureKind.PACKAGE_NOT_FOUND
            if status_code == 404
            else LibraryFetchFailureKind.NETWORK
        )
        raise LibraryFetchError(
            kind, f"GET {url} failed: HTTP {status_code}",
        ) from None
    except urllib.error.URLError as error:
        raise LibraryFetchError(
            LibraryFetchFailureKind.NETWORK,
            f"GET {url} failed: {error.reason}",
        ) from error


HttpGet = Callable[[str], bytes]


@dataclass(frozen=True)
class LibraryCatalogEntry:
    """One library's row in a channel snapshot's ``index.json``."""

    name: str
    version: str
    description: str
    readme_path: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChannelSnapshot:
    """A resolved snapshot: its tag plus every library it carries."""

    channel: str
    tag: str
    libraries: dict[str, LibraryCatalogEntry]


def channel_repo(channel: str) -> str:
    """Return the GitHub source-tree repo for *channel*.

    For example, ``"stable"`` returns ``"ChuMicro/ChuMicro-Libraries"``.

    Raises:
        LibraryFetchError: ``UNKNOWN_CHANNEL`` kind for any other channel.
    """
    try:
        return CHANNEL_REPOS[channel]
    except KeyError:
        raise LibraryFetchError(
            LibraryFetchFailureKind.UNKNOWN_CHANNEL,
            f"unknown channel {channel!r} "
            f"(expected {' or '.join(sorted(CHANNEL_REPOS))})",
        ) from None


def raw_file_url(repo: str, reference: str, path: str) -> str:
    """Raw URL for *path* in *repo* at a git *reference* (tag/branch)."""
    return f"https://raw.githubusercontent.com/{repo}/{reference}/{path}"


def index_url(repo: str, reference: str) -> str:
    """Raw ``index.json`` URL for *repo* at a git *reference* (tag/branch)."""
    return raw_file_url(repo, reference, "index.json")


def tarball_url(repo: str, tag: str) -> str:
    """GitHub source tarball URL for *repo* at *tag*."""
    return f"https://codeload.github.com/{repo}/tar.gz/refs/tags/{tag}"


def _parse_index(channel: str, raw: bytes) -> ChannelSnapshot:
    """Parse a channel ``index.json`` body into a :class:`ChannelSnapshot`."""
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise LibraryFetchError(
            LibraryFetchFailureKind.INDEX_MALFORMED,
            f"{channel} index.json is not valid JSON: {error}",
        ) from error
    if not isinstance(document, dict):
        raise LibraryFetchError(
            LibraryFetchFailureKind.INDEX_MALFORMED,
            f"{channel} index.json top-level must be an object",
        )
    tag = document.get("tag")
    raw_libraries = document.get("libraries")
    if not isinstance(tag, str) or not isinstance(raw_libraries, dict):
        raise LibraryFetchError(
            LibraryFetchFailureKind.INDEX_MALFORMED,
            f"{channel} index.json needs a string 'tag' and a "
            "'libraries' object",
        )
    libraries: dict[str, LibraryCatalogEntry] = {}
    for name, entry in raw_libraries.items():
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("version"), str)
        ):
            raise LibraryFetchError(
                LibraryFetchFailureKind.INDEX_MALFORMED,
                f"{channel} index.json entry {name!r} needs a string "
                "'version'",
            )
        raw_examples = entry.get("examples", [])
        examples = tuple(
            str(item) for item in raw_examples
        ) if isinstance(raw_examples, list) else ()
        libraries[name] = LibraryCatalogEntry(
            name=name,
            version=entry["version"],
            description=str(entry.get("description", "")),
            readme_path=str(entry.get("readme_path", "README.md")),
            examples=examples,
        )
    return ChannelSnapshot(channel=channel, tag=tag, libraries=libraries)


def resolve_snapshot(
    channel: str,
    *,
    tag: str | None = None,
    http_get: HttpGet = _real_http_get,
) -> ChannelSnapshot:
    """Resolve *channel* to a concrete snapshot.

    *tag* ``None`` reads the default-branch ``index.json`` (which
    names the latest snapshot tag and lists that snapshot's
    libraries); a pinned *tag* reads ``index.json`` at that tag
    directly.  One GET either way.
    """
    repo = channel_repo(channel)
    reference = tag if tag is not None else "main"
    snapshot = _parse_index(channel, http_get(index_url(repo, reference)))
    if tag is not None and snapshot.tag != tag:
        # Pinned ref's own index must self-describe as that tag.
        # Otherwise the manifest and the tree would disagree.
        raise LibraryFetchError(
            LibraryFetchFailureKind.INDEX_MALFORMED,
            f"{channel} index.json at {tag} reports tag "
            f"{snapshot.tag!r}",
        )
    return snapshot


def _safe_member_path(into: Path, name: str) -> Path:
    """Resolve archive member *name* under *into*, rejecting traversal.

    ``tarfile``'s ``data`` filter would cover this but only exists on
    3.12+.  This package supports 3.11.
    """
    target = (into / name).resolve()
    if not str(target).startswith(str(into.resolve())):
        raise LibraryFetchError(
            LibraryFetchFailureKind.BAD_ARCHIVE,
            f"archive member escapes extraction dir: {name!r}",
        )
    return target


def extract_library(
    tarball: bytes,
    library_name: str,
    into: Path,
) -> Path:
    """Extract only *library_name*'s subtree from a snapshot *tarball*.

    A GitHub source tarball wraps everything in one ``<repo>-<tag>/``
    directory.  The library lives at ``<repo>-<tag>/<short>/`` where
    ``<short>`` strips the ``chumicro_`` import prefix.  The wrapper
    is stripped, so the tree lands at ``into/<short>/``.  The rest of
    the snapshot is never written.

    Returns the extracted library root (``into/<short>``).
    """
    short_name = library_name.removeprefix("chumicro_")
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            selected: list[tarfile.TarInfo] = []
            for member in archive.getmembers():
                parts = member.name.split("/", 2)
                if len(parts) < 3 or parts[1] != short_name:
                    continue
                member.name = "/".join(parts[1:])
                _safe_member_path(into, member.name)
                selected.append(member)
            if not selected:
                raise LibraryFetchError(
                    LibraryFetchFailureKind.PACKAGE_NOT_FOUND,
                    f"snapshot has no {short_name!r} tree for "
                    f"{library_name!r}",
                )
            archive.extractall(  # noqa: S202 — paths validated above
                into, members=selected,
            )
    except tarfile.TarError as error:
        raise LibraryFetchError(
            LibraryFetchFailureKind.BAD_ARCHIVE,
            f"could not unpack snapshot tarball: {error}",
        ) from error
    return into / short_name


def fetch_snapshot_tarball(
    channel: str,
    snapshot: ChannelSnapshot,
    *,
    http_get: HttpGet = _real_http_get,
) -> bytes:
    """GET *snapshot*'s source tarball once.

    A closure fetch calls this once and then :func:`extract_library`
    per closure member, so one network download covers the whole set.
    """
    return http_get(tarball_url(channel_repo(channel), snapshot.tag))


def fetch_text_file(
    channel: str,
    tag: str,
    path: str,
    *,
    http_get: HttpGet = _real_http_get,
) -> str:
    """GET a single UTF-8 text file from *channel* at *tag*.

    Used for browse drill-in (a library's README or one example):
    one raw file, no tree clone.  Decodes leniently so a stray byte
    never aborts the browser.
    """
    body = http_get(raw_file_url(channel_repo(channel), tag, path))
    return body.decode("utf-8", errors="replace")
