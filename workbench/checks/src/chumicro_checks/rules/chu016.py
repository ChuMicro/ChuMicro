"""CHU016: example imports must resolve on every declared runtime.

``verify_examples`` resolves an example's ``chumicro_*`` imports but
*skips every platform built-in* for hardware-marked files (they
can't import on the host).  So an example declaring both
CircuitPython and MicroPython can ``import board`` (CircuitPython-
only) at module top level and pass that gate, then crash on
MicroPython at first boot.  That is the "flagship example crashes on
the other runtime" drift class this rule closes for example scripts.

A runtime-exclusive module imported at the **module body level**
(not nested under a ``sys.implementation`` branch, a ``try``, or a
function) is a finding when the example's ``__chumicro_runtimes__``
also declares the runtime that module is absent on.  The repo's
correct pattern (runtime-specific imports nested under
``if sys.implementation.name == "circuitpython":`` or inside a
helper function) is module-body-*nested* and therefore never
flagged.

Scope: ``libraries/<pkg>/examples/*.py``.  Acts only on files whose
``__chumicro_runtimes__`` declares a hardware runtime. Single-runtime
examples (a top-level ``import board`` in a CircuitPython-only file)
are correct and not flagged.  Absent ``libraries/``, a silent no-op.

Suppression: ``# noqa: CHU016`` on the offending import line.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU016"

#: Modules that exist only on CircuitPython firmware.
_CIRCUITPYTHON_ONLY: frozenset[str] = frozenset({
    "board", "digitalio", "analogio", "busio", "pwmio", "microcontroller",
    "neopixel", "usb_cdc", "displayio", "rainbowio", "supervisor",
    "wifi", "socketpool",
})

#: Modules that exist only on MicroPython firmware.
_MICROPYTHON_ONLY: frozenset[str] = frozenset({
    "machine", "network", "esp", "esp32", "rp2", "micropython", "bluetooth",
})


def _is_in_library_examples(filepath: Path, repo_root: Path) -> bool:
    if filepath.suffix != ".py":
        return False
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return False
    parts = relative.parts
    return (
        len(parts) >= 3 and parts[0] == "libraries" and parts[2] == "examples"
    )


def _add_runtime_literals(value: ast.expr | None, runtimes: set[str]) -> None:
    """Add the string elements of a tuple / list literal to *runtimes*."""
    if isinstance(value, (ast.Tuple, ast.List)):
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                runtimes.add(elt.value)


def _declared_runtimes(tree: ast.Module) -> set[str]:
    """Runtimes listed in a top-level ``__chumicro_runtimes__``.

    Recognizes both the plain assignment
    (``__chumicro_runtimes__ = (...)``) and the annotated assignment
    (``__chumicro_runtimes__: tuple = (...)``); the latter is an
    ``ast.AnnAssign`` with a single ``target``, not an ``ast.Assign``.
    """
    runtimes: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id == "__chumicro_runtimes__"
                for target in node.targets
            ):
                _add_runtime_literals(node.value, runtimes)
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "__chumicro_runtimes__"
            ):
                _add_runtime_literals(node.value, runtimes)
    return runtimes


def _module_root(name: str | None) -> str:
    return name.split(".")[0] if name else ""


def _top_level_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """``(module_root, lineno)`` for imports that are direct module-body
    statements (i.e. unconditional, not nested under a runtime guard,
    ``try``, ``with``, or function)."""
    imports: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((_module_root(alias.name), node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (no runtime-exclusive root).
            if node.level == 0:
                imports.append((_module_root(node.module), node.lineno))
    return imports


def _conflict(module_root: str, declared: set[str]) -> str | None:
    """Return the declared runtime *module_root* would crash on, if any."""
    if module_root in _CIRCUITPYTHON_ONLY and "micropython" in declared:
        return "micropython"
    if module_root in _MICROPYTHON_ONLY and "circuitpython" in declared:
        return "circuitpython"
    return None


def _check_file(filepath: Path, repo_root: Path) -> list[Finding]:
    if not _is_in_library_examples(filepath, repo_root):
        return []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings
    declared = _declared_runtimes(tree)
    if not declared & {"circuitpython", "micropython"}:
        return []
    source_lines = text.splitlines()
    findings: list[Finding] = []
    for module_root, lineno in _top_level_imports(tree):
        crashes_on = _conflict(module_root, declared)
        if crashes_on is None:
            continue
        if lineno - 1 < len(source_lines) and line_suppresses(
            source_lines[lineno - 1], _RULE_CODE,
        ):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=lineno,
                code=_RULE_CODE,
                message=(
                    f"module-level `import {module_root}` will fail on "
                    f"{crashes_on} but this example's "
                    f"__chumicro_runtimes__ declares it; guard the import "
                    f"under a `sys.implementation.name` branch (or inside "
                    f"the function that needs it)"
                ),
            )
        )
    return findings


class CHU016_ExampleRuntimeImports(Rule):
    code = _RULE_CODE
    description = (
        "example imports must resolve on every declared runtime"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        libraries_dir = repo_root / "libraries"
        if not libraries_dir.is_dir():
            return []
        findings: list[Finding] = []
        for filepath in iter_text_files(libraries_dir, suffixes=(".py",)):
            findings.extend(_check_file(filepath, repo_root))
        return findings


CHU016 = CHU016_ExampleRuntimeImports()
