"""Read ``__chumicro_runtimes__`` markers from library source files.

A module-level marker declares which runtimes a file is meant for::

    __chumicro_runtimes__ = ("circuitpython",)

The bundle pipeline uses this marker to filter per-runtime ``.mpy``
bundles.  The same filter applies on deploy paths
(``DirectorySource`` / ``ImportGraphSource`` / the per-runtime
transports), so wrong-runtime files never land on a board.

:func:`file_targets_runtime` accepts a single runtime name (concrete
target) or a frozenset of runtimes (set-of-acceptable-targets — used by
the source bundle to drop CPython-only files while keeping everything
device-bound).

A separate, runtime-independent marker — ``__chumicro_test_support__
= True`` — flags a library's ``testing.py`` fakes as test-support:
filtered out of bundles and product / app / functional deploys, but
staged by the on-device unit sweep.  :func:`is_test_support_module`
reads it.

The readers use :func:`ast.parse` (no execution) — runtime-specific
files commonly import device-only modules at top level
(``import wifi``, ``import esp32``) that fail on the host.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Canonical runtime names recognized in ``__chumicro_runtimes__``
#: markers.  Sub-runtime names like ``micropython_esp32`` are accepted
#: at parse time but currently fold into ``micropython`` for matching —
#: both MP variants share the same ``mpy6/`` bundle today and the same
#: deploy-time filter.
KNOWN_RUNTIMES: frozenset[str] = frozenset({
    "circuitpython", "micropython",
    "micropython_esp32", "micropython_rp2",
    "cpython",
})

#: Runtimes that land on a microcontroller.  The source bundle passes
#: this set as *target_runtime* so files marked exclusively for
#: ``cpython`` drop out — they only belong in the PyPI sdist / wheel,
#: which doesn't go through the bundle pipeline.
DEVICE_RUNTIMES: frozenset[str] = frozenset({"circuitpython", "micropython"})


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


def is_test_support_module(python_file: Path) -> bool:
    """Return ``True`` when *python_file* declares ``__chumicro_test_support__``.

    A test-support module (a library's ``testing.py`` fakes) exists
    only to support tests and must never reach a shipped product.  It
    is filtered out of every bundle and every product / app /
    functional device deploy, independent of runtime — the fakes run
    on every runtime (the cross-runtime unit suite executes them on
    MicroPython and CircuitPython).  The on-device unit sweep
    (``--target device-unit``) is the one path that stages them,
    because the cross-runtime unit tests legitimately import the
    fakes.

    The marker is a top-level ``__chumicro_test_support__ = True``
    assignment.  Read via :func:`ast.parse` (no execution), matching
    :func:`read_runtime_marker`.
    """
    try:
        tree = ast.parse(python_file.read_text(), filename=str(python_file))
    except (OSError, SyntaxError):
        return False  # Unreadable / unparseable → not test-support (fail-safe).
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [
            target.id for target in node.targets if isinstance(target, ast.Name)
        ]
        if "__chumicro_test_support__" not in targets:
            continue
        return isinstance(node.value, ast.Constant) and node.value.value is True
    return False


def file_targets_runtime(
    python_file: Path,
    *,
    target_runtime: str | frozenset[str] | None,
) -> bool:
    """Return ``True`` when *python_file* should ship to *target_runtime*.

    ``target_runtime=None`` is the unfiltered case — every file matches.
    This is the legacy default for deploy paths that want the prior
    "ship everything" behavior; PyPI sdist / wheel building doesn't
    pass through this function.

    A string target (``"circuitpython"`` / ``"micropython"`` /
    ``"cpython"``) means "this single concrete runtime" — a marked file
    matches only when its marker contains the target.  Used by per-
    runtime mpy bundles and by transports that know their target.

    A frozenset target means "any of these runtimes" — a marked file
    matches when its marker overlaps the set.  Used by the source
    bundle (:data:`DEVICE_RUNTIMES`) to drop ``("cpython",)``-only
    files while keeping every CP- and MP-bound file.

    Files without a marker match every target (default-safe).
    Sub-runtime markers (``micropython_esp32`` etc.) fold into
    ``micropython`` since both MP variants share one bundle today.
    """
    if target_runtime is None:
        return True
    marker = read_runtime_marker(python_file)
    if marker is None:
        return True  # Default-safe: unmarked files ship everywhere.
    folded = frozenset(
        name.split("_", 1)[0] if name.startswith("micropython_") else name
        for name in marker
    )
    targets = (
        frozenset({target_runtime}) if isinstance(target_runtime, str) else target_runtime
    )
    return bool(folded & targets)
