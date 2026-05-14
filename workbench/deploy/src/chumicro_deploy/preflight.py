"""Deploy-time pre-flight checks.

Currently checks for libraries flagged as ``requires_flash`` in their
``pyproject.toml``'s ``[tool.chumicro]`` block.  When the user
requested RAM mode but the deploy graph contains a flagged library,
the deployer auto-switches to flash mode for the run and prints a
human-readable explanation — RAM-mode deploys exec each library's
source inline and OOM on smaller boards once the deploy graph crosses
a few hundred KB.

Public API:

* :func:`find_libraries_requiring_flash` — walks a list of host paths
  to find every unique containing ``pyproject.toml``, reads
  ``[tool.chumicro].requires_flash`` from each, returns the names
  of the libraries flagged ``true``.

The function is host-paths-in / library-names-out so callers can
build the host-paths list from any source shape (an
:class:`ImportGraphSource`'s ``host_paths()``, a hand-curated list
for tests, etc.) and the result is a sorted list of pip-name-shaped
strings ready to interpolate into a user-facing message.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def find_libraries_requiring_flash(host_paths: list[Path]) -> list[str]:
    """Return library names with ``[tool.chumicro].requires_flash = true``.

    Walks each path in *host_paths* up the directory tree until a
    ``pyproject.toml`` is found, reads its
    ``[tool.chumicro].requires_flash`` flag, and collects the
    ``[project].name`` values of every flagged library.  Skips paths
    with no containing pyproject and pyprojects that fail to parse —
    pre-flight is best-effort, not authoritative.

    Args:
        host_paths: Filesystem paths the deploy graph drew files
            from (typically :meth:`ImportGraphSource.host_paths`).

    Returns:
        Sorted list of unique pip-name-shaped library names
        (``["chumicro-mqtt", "chumicro-requests"]``).  Empty list
        when no flagged library is in the graph.
    """
    flagged: set[str] = set()
    seen_pyprojects: set[Path] = set()
    for path in host_paths:
        pyproject = _find_pyproject(path)
        if pyproject is None or pyproject in seen_pyprojects:
            continue
        seen_pyprojects.add(pyproject)
        data = _load_pyproject(pyproject)
        if data is None:
            continue
        if not data.get("tool", {}).get("chumicro", {}).get("requires_flash", False):
            continue
        name = data.get("project", {}).get("name")
        if name:
            flagged.add(name)
    return sorted(flagged)


def _find_pyproject(start: Path) -> Path | None:
    """Walk up from *start* until a ``pyproject.toml`` is found.

    Returns the first ``pyproject.toml`` whose parent is an ancestor
    of *start*, or ``None`` when the walk reaches the filesystem root
    without finding one.
    """
    for ancestor in [start, *start.parents]:
        candidate = ancestor / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _load_pyproject(pyproject: Path) -> dict | None:
    """Parse *pyproject* once and return its full document, or ``None``.

    Pre-flight is best-effort: parse errors and unreadable files yield
    ``None`` so callers fall through to "RAM mode is fine."
    """
    try:
        with open(pyproject, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
