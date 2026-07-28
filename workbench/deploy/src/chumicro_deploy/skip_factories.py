"""Read ``__chumicro_skip_factories__`` markers and compute the deploy skip set.

Users opt out of chumicro factory submodules per-entrypoint via a
module-level constant the walker reads at AST time::

    __chumicro_skip_factories__ = (
        "sockets_factory",                    # family: every chumicro_*.sockets_factory
        "chumicro_websockets.tls_factory",    # exact: this one module
    )

The reader uses :func:`ast.parse` and never executes the file, so an
entrypoint that imports device-only modules (``import wifi``,
``import board``) remains readable on the host.

This module exposes three primitives the walker glues together:

* :func:`read_skip_factories_marker` pulls the constant from one file.
* :func:`discover_factory_modules` lists every ``chumicro_*/<name>_factory.py``
  under the search paths.
* :func:`resolve_skip_targets` matches the user's entries against the
  discovered list with family + exact semantics, surfacing typos.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: A factory submodule's filename, before the ``.py`` extension.  Must
#: start with a letter so a stray ``_foo_factory.py`` (private helper,
#: not a user-facing opt-out target) isn't picked up as discoverable.
_FACTORY_STEM = re.compile(r"^[a-z][a-z0-9_]*_factory$")


def read_skip_factories_marker(entrypoint_path: Path) -> tuple[str, ...] | None:
    """Return entries from ``__chumicro_skip_factories__`` on *entrypoint_path*.

    The marker is a top-level tuple/list assignment of string literals.
    Returns ``None`` when no marker is declared (no skipping).  Returns
    an empty tuple only if the marker is explicitly empty (legal but
    useless; the walker treats it as no-op).

    Read via :func:`ast.parse`, which never executes the file, so
    device-only imports at the top of *entrypoint_path* don't trip the
    reader.
    """
    try:
        tree = ast.parse(entrypoint_path.read_text(), filename=str(entrypoint_path))
    except (SyntaxError, OSError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [
            target.id for target in node.targets if isinstance(target, ast.Name)
        ]
        if "__chumicro_skip_factories__" not in targets:
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        entries: list[str] = []
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                entries.append(element.value)
        return tuple(entries)
    return None


def discover_factory_modules(search_paths: list[Path]) -> dict[str, str]:
    """Return ``{fully_qualified_module: family_stem}`` for every discoverable factory.

    Walks each search path's immediate ``chumicro_*`` package directories
    looking for top-level ``<stem>_factory.py`` files where ``<stem>``
    starts with a letter.  Subdirectory placement (e.g.
    ``chumicro_foo/factories/sockets_factory.py``) is intentionally
    out-of-scope: the convention is a flat file at the package root.

    The returned dict's keys are dotted module names like
    ``chumicro_mqtt.sockets_factory``.  Values are the bare stem
    (``sockets_factory``) used for family-form matching.

    First-search-path-wins: if two search paths both contain
    ``chumicro_mqtt/sockets_factory.py`` (unusual), the first wins.
    """
    discovered: dict[str, str] = {}
    for search_path in search_paths:
        if not search_path.is_dir():
            continue
        for library_dir in search_path.iterdir():
            if not library_dir.is_dir() or not library_dir.name.startswith("chumicro_"):
                continue
            for factory_file in library_dir.glob("*_factory.py"):
                stem = factory_file.stem
                if not _FACTORY_STEM.match(stem):
                    continue
                module_name = f"{library_dir.name}.{stem}"
                discovered.setdefault(module_name, stem)
    return discovered


def resolve_skip_targets(
    skip_entries: tuple[str, ...],
    discovered: dict[str, str],
) -> tuple[dict[str, frozenset[str]], tuple[str, ...]]:
    """Resolve user-supplied skip entries against the discovered factory list.

    Returns ``(per_entry, unmatched)``.

    * ``per_entry`` is a mapping of each user-written entry to the set of
      fully-qualified factory module names it matched.  Order of the
      keys preserves the order the user wrote them.  The union of all
      values is the skip set; the per-entry mapping enables dead-skip
      diagnostics (an entry is dead when none of its matched modules'
      parent libraries are imported).
    * ``unmatched`` holds user entries that matched zero discovered modules,
      preserved in the order the user wrote them.  Treat a non-empty
      ``unmatched`` as a typo guard and raise: silently shipping the
      unwanted library is worse than refusing to deploy.

    Two match shapes:

    * Entry contains a ``.``: exact match against a discovered module
      path (``chumicro_mqtt.sockets_factory``).
    * Entry contains no ``.``: family match against the file stem
      (``sockets_factory`` matches every ``chumicro_*.sockets_factory``).
    """
    per_entry: dict[str, frozenset[str]] = {}
    unmatched: list[str] = []
    for entry in skip_entries:
        if "." in entry:
            if entry in discovered:
                per_entry[entry] = frozenset({entry})
            else:
                unmatched.append(entry)
            continue
        family_hits = frozenset(
            module_name
            for module_name, family in discovered.items()
            if family == entry
        )
        if family_hits:
            per_entry[entry] = family_hits
        else:
            unmatched.append(entry)
    return per_entry, tuple(unmatched)
