"""Transitive chumicro-dependency resolution for the library CLI.

``library add`` pulls a library and the chumicro libraries it depends
on.  The dependency graph is read from each fetched library's own
``pyproject.toml`` ``[project].dependencies``.  Only runtime
dependencies count.  The ``[test]`` extra's chumicro entries are test
infrastructure, not what the board runs.

Two pieces, both pure:

* :func:`chumicro_dependencies` returns the direct chumicro deps of
  one ``pyproject.toml``, as import names (``chumicro-mqtt`` becomes
  ``chumicro_mqtt``).
* :func:`transitive_closure` returns the full set reachable from some
  roots, given an injected ``deps_of`` callback.  Production callers
  pass a ``deps_of`` that fetches and reads pyproject files.  Tests
  pass a plain dict.  The recursion is cycle-safe and
  order-deterministic so the user sees a stable tree.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from pathlib import Path

#: Leading distribution-name token of a PEP 508 requirement string,
#: stopping at the first version specifier, extra, marker, or whitespace.
_REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")


def _distribution_to_import_name(distribution: str) -> str:
    """``chumicro-http-server`` -> ``chumicro_http_server``."""
    return distribution.strip().lower().replace("-", "_")


def chumicro_dependencies(pyproject_path: Path) -> list[str]:
    """Return the direct chumicro runtime deps of *pyproject_path*.

    Reads ``[project].dependencies``, keeps entries whose distribution
    name starts with ``chumicro-``, and returns them as import names,
    sorted and de-duplicated.  A missing file or missing/empty
    ``dependencies`` list yields ``[]``.
    """
    if not pyproject_path.is_file():
        return []
    with pyproject_path.open("rb") as handle:
        pyproject = tomllib.load(handle)
    raw_deps = pyproject.get("project", {}).get("dependencies", [])

    names: set[str] = set()
    for requirement in raw_deps:
        match = _REQUIREMENT_NAME.match(requirement)
        if match is None:
            continue
        distribution = match.group(1)
        if distribution.lower().startswith("chumicro-"):
            names.add(_distribution_to_import_name(distribution))
    return sorted(names)


def transitive_closure(
    roots: list[str],
    deps_of: Callable[[str], list[str]],
) -> list[str]:
    """Return *roots* plus every chumicro library reachable from them.

    *deps_of* maps an import name to its direct chumicro deps (also
    import names).  Breadth-first from *roots* in the given order;
    the result is deterministic and each name appears once.
    Self-references and cycles terminate cleanly.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    queue: list[str] = list(roots)
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
        for dependency in deps_of(name):
            if dependency not in seen:
                queue.append(dependency)
    return ordered
