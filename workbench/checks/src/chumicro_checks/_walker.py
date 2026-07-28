"""Shared file-walker helpers.

Rules that scan multiple files use :func:`iter_text_files` to traverse
directory trees with a consistent set of build-artefact exclusions and
suffix filtering.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

#: Directory names skipped during recursive walks: build artefacts,
#: cache directories, vendored deps, IDE / CI scratch.
EXCLUDED_DIRECTORY_NAMES: frozenset[str] = frozenset({
    "__pycache__",
    "dist",
    "build",
    "site",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "node_modules",
    ".git",
    ".tools",
})

#: Suffix substrings any of whose presence on a path component skips that path.
_EXCLUDED_SUFFIXES: tuple[str, ...] = (".egg-info",)


def _is_excluded(path: Path) -> bool:
    parts = path.parts
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in parts):
        return True
    return any(part.endswith(_EXCLUDED_SUFFIXES) for part in parts)


def iter_text_files(
    root: Path, *, suffixes: Iterable[str]
) -> Iterator[Path]:
    """Yield every file under *root* whose suffix is in *suffixes*.

    Skips build / cache directories listed in :data:`EXCLUDED_DIRECTORY_NAMES`
    and any path component ending with ``.egg-info``.  Output order is
    deterministic (sorted recursive glob).

    If *root* is itself a file with a matching suffix, yield just that
    file.  If *root* doesn't exist or is neither a file nor a directory,
    yield nothing, so callers don't need to pre-check existence.
    """
    suffix_set = tuple(suffixes)
    if root.is_file():
        if root.suffix in suffix_set and not _is_excluded(root):
            yield root
        return
    if not root.is_dir():
        return
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.suffix not in suffix_set:
            continue
        if _is_excluded(candidate):
            continue
        yield candidate
