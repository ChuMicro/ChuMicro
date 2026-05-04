"""Read ``__chumicro_runtimes__`` markers from library source files.

Decision 0037 introduced a module-level marker that declares which
runtimes a file is meant for::

    __chumicro_runtimes__ = ("circuitpython",)

The bundle pipeline (``scripts/bundle_manager.py``) uses this marker to
filter per-runtime ``.mpy`` bundles.  Decision 0044 extends the same
filter to deploy paths (``DirectorySource`` / ``ImportGraphSource`` /
the per-runtime transports), so wrong-runtime files no longer land on
a board during ``chumicro_deploy`` / ``chumicro_workspace deploy`` /
``pytest-device`` staging.

The reader uses :func:`ast.parse` (no execution) — runtime-specific
files commonly import device-only modules at top level
(``import wifi``, ``import esp32``) that fail on the host.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Canonical runtime names recognised in ``__chumicro_runtimes__``
#: markers.  Sub-runtime names like ``micropython_esp32`` are accepted
#: at parse time but currently fold into ``micropython`` for matching —
#: both MP variants share the same ``mpy6/`` bundle today and the same
#: deploy-time filter.
KNOWN_RUNTIMES: frozenset[str] = frozenset({
    "circuitpython", "micropython",
    "micropython_esp32", "micropython_rp2",
    "cpython",
})


def read_runtime_marker(python_file: Path) -> frozenset[str] | None:
    """Return the ``__chumicro_runtimes__`` set declared in *python_file*.

    The marker is a top-level tuple/list assignment of runtime name
    strings.  Returns ``None`` when no marker is declared (file is
    universal — ships everywhere).  Returns an empty frozenset only if
    the marker is explicitly empty (unusual but legal).

    Read via :func:`ast.parse` — never executes the file, so adapter
    files that import device-only modules at top level remain readable
    on the host.
    """
    try:
        tree = ast.parse(python_file.read_text(), filename=str(python_file))
    except SyntaxError:
        return None  # Treat unparseable files as universal — fail-safe.
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "__chumicro_runtimes__" not in targets:
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        names: list[str] = []
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                names.append(element.value)
        return frozenset(names)
    return None


def file_targets_runtime(
    python_file: Path,
    *,
    target_runtime: str | None,
) -> bool:
    """Return ``True`` when *python_file* should ship to *target_runtime*.

    ``target_runtime=None`` is the universal (unfiltered) case — every
    file matches.  This matches the source bundle / sdist behavior per
    Decision 0037.

    Otherwise, a file with no marker matches every target (default-safe);
    a file with a marker matches only when *target_runtime* appears in
    the marker.  Sub-runtime markers (``micropython_esp32`` etc.) fold
    into ``micropython`` since both MP variants share one bundle today.
    """
    if target_runtime is None:
        return True
    marker = read_runtime_marker(python_file)
    if marker is None:
        return True  # Default-safe: unmarked files ship everywhere.
    folded = {
        name.split("_", 1)[0] if name.startswith("micropython_") else name
        for name in marker
    }
    return target_runtime in folded
