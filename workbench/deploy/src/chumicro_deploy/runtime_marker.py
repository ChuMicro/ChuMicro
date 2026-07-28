"""Read ``__chumicro_runtimes__`` markers from library source files.

A module-level marker declares which runtimes a file is meant for::

    __chumicro_runtimes__ = ("circuitpython",)

Bundle filtering and per-runtime deploy filtering both consume this
marker so wrong-runtime files never land on a board.

Three readers: :func:`file_targets_runtime`,
:func:`is_test_support_module`, :func:`is_host_only_test`.  See each
one's docstring for the marker shape it consumes.

The readers use :func:`ast.parse` (no execution), because
runtime-specific files commonly import device-only modules at top
level (``import wifi``, ``import esp32``) that fail on the host.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Runtime names recognized in ``__chumicro_runtimes__`` markers.
#: Sub-runtime names like ``micropython_esp32`` are accepted at parse
#: time but fold into ``micropython`` for matching: both MP variants
#: share the same ``mpy6/`` bundle and deploy-time filter.
KNOWN_RUNTIMES: frozenset[str] = frozenset({
    "circuitpython", "micropython",
    "micropython_esp32", "micropython_rp2",
    "cpython",
})

#: Runtimes that land on a microcontroller.  Passing this set as
#: *target_runtime* drops files marked exclusively for ``cpython``;
#: those only belong in the PyPI sdist / wheel, which doesn't go
#: through the bundle pipeline.
DEVICE_RUNTIMES: frozenset[str] = frozenset({"circuitpython", "micropython"})


def _top_level_assignment_value(
    python_file: Path, marker_name: str,
) -> ast.expr | None:
    """Return the AST value node of a top-level ``<marker_name> = ...``.

    Returns ``None`` when the file is unreadable, unparseable, or the
    marker is not present at module scope.
    """
    try:
        tree = ast.parse(python_file.read_text(), filename=str(python_file))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [
            target.id for target in node.targets if isinstance(target, ast.Name)
        ]
        if marker_name in targets:
            return node.value
    return None


def read_runtime_marker(python_file: Path) -> frozenset[str] | None:
    """Return the ``__chumicro_runtimes__`` set declared in *python_file*.

    The marker is a top-level tuple/list assignment of runtime name
    strings.  Returns ``None`` when no marker is declared (file is
    universal and ships everywhere).  Returns an empty frozenset only if
    the marker is explicitly empty (unusual but legal).
    """
    value = _top_level_assignment_value(python_file, "__chumicro_runtimes__")
    if not isinstance(value, (ast.Tuple, ast.List)):
        return None
    return frozenset(
        element.value
        for element in value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )


def is_test_support_module(python_file: Path) -> bool:
    """Return ``True`` when *python_file* declares ``__chumicro_test_support__``.

    A test-support module (a library's ``testing.py`` fakes) exists
    only to support tests and must never reach a shipped product.
    The marker is runtime-independent because the fakes run on every
    runtime.

    The marker is a top-level ``__chumicro_test_support__ = True``
    assignment.
    """
    value = _top_level_assignment_value(python_file, "__chumicro_test_support__")
    return isinstance(value, ast.Constant) and value.value is True


def is_host_only_test(python_file: Path) -> bool:
    """Return ``True`` when *python_file* declares ``__chumicro_host_only__``.

    A host-only test file runs on CPython and the MicroPython /
    CircuitPython unix-ports but never on real silicon: it exercises
    a runtime-specific source module through host fakes and asserts
    off-target behaviour (e.g. ``RuntimeError`` because the device
    module is absent on the host).  On real silicon both branches
    fail: the wrong-runtime device-side filter strips the imported
    module, and a matching board fails the off-target assertion.

    Orthogonal to ``__chumicro_runtimes__`` (the files run on every
    host interpreter, so no runtime subset describes them) and to
    ``__chumicro_test_support__`` (that gates *shipping* of
    ``testing.py`` fakes; this gates *collection* of test files for
    the on-device sweep).

    The marker is a top-level ``__chumicro_host_only__ = True``
    assignment.
    """
    value = _top_level_assignment_value(python_file, "__chumicro_host_only__")
    return isinstance(value, ast.Constant) and value.value is True


def file_targets_runtime(
    python_file: Path,
    *,
    target_runtime: str | frozenset[str] | None,
) -> bool:
    """Return ``True`` when *python_file* should ship to *target_runtime*.

    ``target_runtime=None`` is the unfiltered case, and every file
    matches.

    A string target (``"circuitpython"`` / ``"micropython"`` /
    ``"cpython"``) means "this single concrete runtime", so a marked
    file matches only when its marker contains the target.

    A frozenset target means "any of these runtimes", so a marked
    file matches when its marker overlaps the set, e.g. dropping
    ``("cpython",)``-only files while keeping every CP- and MP-bound
    file.

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
