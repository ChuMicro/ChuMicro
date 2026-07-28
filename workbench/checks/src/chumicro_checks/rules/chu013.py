"""CHU013: no mid-tick ``ticks_ms`` refetch in runner-shaped methods.

Runner-shaped services receive ``now_ms`` once per tick from the
runner and must reuse that value across every deadline computed that
tick.  Refetching the current instant inside a method that already has
``now_ms`` in scope produces a second timestamp microseconds later,
breaking the "one shared instant per tick" guarantee.  Every
dependency-injection spelling of the fetch is flagged:

* ``self._ticks.ticks_ms()`` / ``self._ticks_ms()``: a provider held
  on ``self``.
* ``ticks.ticks_ms()``: a provider passed in as a parameter or bound
  to a local.
* ``ticks_ms()``: a bare call to a name imported from the timing
  library (``from chumicro_timing import ticks_ms``).

This rule flags any such refetch inside a function that takes a
``now_ms`` parameter, unless the call is guarded by an
``if now_ms is None:`` branch. The codified pattern for helpers
shared between tick-path callers (which pass ``now_ms``) and
user-entry callers (which don't).

Scope: ``libraries/<pkg>/src/`` only.  Tests, examples, and
host-side workbench code may refetch freely.  Suppress with
``# noqa: CHU013`` when matching an upstream API or for any other
case where the rule legitimately doesn't apply.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU013"

#: Method-call attribute names that count as a tick-fetch.  Matches
#: ``self._ticks.ticks_ms()`` and the ``self._ticks_ms()`` shape.
_TICKS_MS_ATTRS: frozenset[str] = frozenset({"ticks_ms", "_ticks_ms"})


def _is_in_library_source(filepath: Path, repo_root: Path) -> bool:
    """Return whether *filepath* lives under ``libraries/<pkg>/src/``."""
    if filepath.suffix != ".py":
        return False
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) >= 3 and parts[0] == "libraries" and parts[2] == "src"


def _scan_libraries(repo_root: Path) -> list[Path]:
    libraries_dir = repo_root / "libraries"
    if not libraries_dir.is_dir():
        return []
    return [libraries_dir]


def _function_takes_now_ms(func: ast.FunctionDef) -> bool:
    args = func.args
    for arg in list(args.args) + list(args.kwonlyargs):
        if arg.arg == "now_ms":
            return True
    return False


def _is_ticks_ms_call(node: ast.Call) -> bool:
    """Return whether *node* refetches the current tick with zero args.

    Matches every dependency-injection spelling of the fetch:

    * ``ticks_ms()``: a bare call to an imported name.
    * ``<name>.ticks_ms()`` / ``<name>._ticks_ms()``: a provider held
      in a parameter, local, or on ``self`` (``self._ticks_ms()``).
    * ``<name>.<attr>.ticks_ms()``: a provider one attribute deep
      (``self._ticks.ticks_ms()``).
    """
    if node.args or node.keywords:
        return False
    callee = node.func
    if isinstance(callee, ast.Name):
        return callee.id == "ticks_ms"
    if not isinstance(callee, ast.Attribute):
        return False
    if callee.attr not in _TICKS_MS_ATTRS:
        return False
    # callee.value is the bit before ``.ticks_ms``: a bare name
    # (``ticks`` / ``self``) or one attribute deep (``self._ticks``).
    receiver = callee.value
    if isinstance(receiver, ast.Name):
        return True
    if isinstance(receiver, ast.Attribute):
        return isinstance(receiver.value, ast.Name)
    return False


def _is_now_ms_is_none_test(test: ast.expr) -> bool:
    """Return whether *test* is the ``now_ms is None`` shape."""
    if not isinstance(test, ast.Compare):
        return False
    if not isinstance(test.left, ast.Name) or test.left.id != "now_ms":
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Is):
        return False
    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value is None


def _guarded_ticks_ms_calls(func: ast.FunctionDef) -> set[int]:
    """Return line numbers of ``ticks_ms`` calls inside an
    ``if now_ms is None:`` branch. These are the user-entry fallback
    and must not be flagged."""
    guarded: set[int] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        if not _is_now_ms_is_none_test(node.test):
            continue
        for inner in node.body:
            for call in ast.walk(inner):
                if isinstance(call, ast.Call) and _is_ticks_ms_call(call):
                    guarded.add(call.lineno)
    return guarded


def _check_function(
    func: ast.FunctionDef, filepath: Path, source_lines: list[str]
) -> list[Finding]:
    if not _function_takes_now_ms(func):
        return []
    guarded = _guarded_ticks_ms_calls(func)
    findings: list[Finding] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call) or not _is_ticks_ms_call(node):
            continue
        if node.lineno in guarded:
            continue
        line = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
        if line_suppresses(line, _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=node.lineno,
                code=_RULE_CODE,
                message=(
                    f"refetching ticks_ms() inside {func.name!r} drops the "
                    f"runner-supplied now_ms; use the parameter instead "
                    f"(or guard the refetch with ``if now_ms is None``)"
                ),
            )
        )
    return findings


def _iter_methods(tree: ast.Module) -> list[ast.FunctionDef]:
    methods: list[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    methods.append(child)
        elif isinstance(node, ast.FunctionDef):
            methods.append(node)
    return methods


def _check_file(filepath: Path, repo_root: Path) -> list[Finding]:
    if not _is_in_library_source(filepath, repo_root):
        return []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings
    source_lines = text.splitlines()
    findings: list[Finding] = []
    for method in _iter_methods(tree):
        findings.extend(_check_function(method, filepath, source_lines))
    return findings


class CHU013_TicksRefetch(Rule):
    code = _RULE_CODE
    description = (
        "no mid-tick ticks_ms refetch; use the runner-supplied now_ms"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        roots = _scan_libraries(repo_root)
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            for filepath in iter_text_files(root, suffixes=(".py",)):
                findings.extend(_check_file(filepath, repo_root))
        return findings


CHU013 = CHU013_TicksRefetch()
