"""CHU009 + CHU010: no silent-pass / no-assertion patterns in test bodies.

Two paired rules, both targeting library-side test files
(``libraries/<name>/tests/test_*.py`` and
``libraries/<name>/functional_tests/test_*.py``).  They share scope
detection and AST walking but emit distinct findings under distinct
codes.

CHU009: no ``return`` / ``pass`` that makes a test PASS without
asserting.  Two shapes are flagged::

    def test_thing() -> None:
        if not _PRECONDITION:
            log(...)
            return            # last stmt of an if body, branch skips
                              # every assertion below
        ...

    def test_other() -> None:
        setup()
        return                # early bare return, orphans the
        assert result()       # assertions after it

    def test_hardware() -> None:
        try:
            probe = open_hardware()
        except OSError:
            return            # ends the test, every assertion below
        assert probe.ready    # never runs

A trailing ``return`` at the end of an ``except`` handler, a ``for`` /
``while`` body (or its ``else``), a ``with`` body, or a ``try``
``finally`` body is flagged the same way.  Each ends the test early and
orphans the assertions after the enclosing statement.  A ``pass`` in
those positions is left alone: an ``except OSError: pass`` swallowing a
cleanup error skips nothing and is a normal idiom.

The test_harness runner reports any test that returns without
raising as PASS, and pytest does the same.  Use
``chumicro_test_harness.skip(reason)`` (or ``raise AssertionError(...)``
for "shouldn't have been reached" cases) instead.

CHU010: a test function must contain at least one assertion::

    def test_close_idempotent():
        sock.close()
        sock.close()       # no assertion, passes regardless of behavior

Without an explicit ``assert``, ``raise``, ``pytest.fail``,
``pytest.raises``, ``chumicro_test_harness.skip``, etc., the only
way the test fails is a crash inside the body.

Self-scope: only files under ``libraries/<pkg>/tests/`` or
``libraries/<pkg>/functional_tests/`` matching ``test_*.py`` are
checked.  In a tree without a ``libraries/`` directory, both rules
return no findings, a silent no-op.

Suppression: ``# noqa: CHU009`` / ``# noqa: CHU010`` on the
flagged line (or on the function header for CHU010).
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_CHU009 = "CHU009"
_CHU010 = "CHU010"

#: Subdirectories of each library where these rules apply.
_SCOPE_DIRECTORIES: tuple[str, ...] = ("tests", "functional_tests")

#: Function-call names that count as a real assertion.  The rightmost
#: dotted segment is checked, so ``pytest.skip`` and ``skip``,
#: ``pytest.raises`` and ``raises``, etc. all match.
_ASSERTION_CALL_NAMES: frozenset[str] = frozenset({
    "fail",
    "skip",
    "skip_module",
    "raises",
    "importorskip",
    "AssertionError",
})


def _is_in_scope(filepath: Path, repo_root: Path) -> bool:
    """Return whether *filepath* is a library test file we lint."""
    if filepath.suffix != ".py":
        return False
    if not filepath.name.startswith("test_"):
        return False
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return False
    parts = relative.parts
    if len(parts) < 4 or parts[0] != "libraries":
        return False
    return parts[2] in _SCOPE_DIRECTORIES


def _scan_libraries(repo_root: Path) -> list[Path]:
    """Return ``[libraries_dir]`` if it exists, else an empty list."""
    libraries_dir = repo_root / "libraries"
    if not libraries_dir.is_dir():
        return []
    return [libraries_dir]


def _iter_test_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Yield every ``def test_*`` at module level or inside ``Test*`` classes."""
    functions: list[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            functions.append(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef)
                    and child.name.startswith("test_")
                ):
                    functions.append(child)
    return functions


def _callable_tail_name(node: ast.expr) -> str | None:
    """Return the rightmost dotted segment of a call's callable."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _function_has_assertion(func: ast.FunctionDef) -> bool:
    """Return whether *func*'s own control flow contains anything that can fail it.

    Walks the test body's compound statements (if / for / while / with /
    try) but stops at nested ``def`` / ``lambda`` / ``class``: an
    ``assert`` inside a callback the test registers but never drives
    cannot fail the test, so it must not satisfy CHU010.
    """
    stack = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Assert | ast.Raise):
            return True
        if isinstance(node, ast.Call):
            name = _callable_tail_name(node.func)
            if name in _ASSERTION_CALL_NAMES:
                return True
        for child in ast.iter_child_nodes(node):
            stack.append(child)
    return False


def _source_line(source_lines: list[str], lineno: int) -> str:
    return source_lines[lineno - 1] if 0 < lineno <= len(source_lines) else ""


def _ifs_in_scope(func: ast.FunctionDef):
    """Yield ``ast.If`` nodes in *func*'s own control flow.

    Descends compound statements (if / for / while / with / try) but
    stops at nested ``def`` / ``lambda`` / ``class``. A ``return``
    inside a closure (a socket factory, a callback) is that callable's
    logic, not the test silently passing.
    """
    stack = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.If):
            yield node
        for child in ast.iter_child_nodes(node):
            stack.append(child)


def _return_bodies_in_scope(func: ast.FunctionDef):
    """Yield the bodies of non-``if`` compound statements in *func*.

    Descends compound statements but stops at nested ``def`` /
    ``lambda`` / ``class`` (same closure carve-out as
    :func:`_ifs_in_scope`).  Yields the body list of every
    ``except`` handler, ``for`` / ``while`` body and ``else``,
    ``with`` body, and ``try`` ``finally`` body: the positions where a
    trailing ``return`` ends the test early.  The ``try`` body and the
    ``if`` family are handled elsewhere.
    """
    stack = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.ExceptHandler):
            yield node.body
        elif isinstance(node, ast.For | ast.AsyncFor | ast.While):
            yield node.body
            if node.orelse:
                yield node.orelse
        elif isinstance(node, ast.With | ast.AsyncWith):
            yield node.body
        elif isinstance(node, ast.Try) and node.finalbody:
            yield node.finalbody
        for child in ast.iter_child_nodes(node):
            stack.append(child)


def _silent_return_findings(
    func: ast.FunctionDef, filepath: Path, source_lines: list[str]
) -> list[Finding]:
    """Flag any control flow that makes a test PASS without asserting.

    Three shapes, all reported as the test silently passing:

    * ``Return`` / ``Pass`` as the **last** statement of any ``if``
      body, which makes the guarded branch skip every assertion below it.
    * a bare ``return`` / ``pass`` that is a direct statement of the
      test body and not its final statement, an early exit that
      orphans the assertions after it.
    * ``Return`` as the last statement of an ``except`` handler, a
      ``for`` / ``while`` body or ``else``, a ``with`` body, or a
      ``try`` ``finally`` body: the same early-exit skip, one level
      deeper.  ``Pass`` in those positions is deliberately not flagged
      (it skips nothing).

    A bare ``return`` / ``pass`` as the test body's **final** statement is
    deliberately not flagged: a trailing exit after the assertions ran is
    harmless, and a test that only ``pass``es with no assertion is caught
    by CHU010 instead.
    """
    findings: list[Finding] = []
    seen_lines: set[int] = set()

    def _emit(report_line: int, suppress_lines: tuple[str, ...], kind_node) -> None:
        if report_line in seen_lines:
            return
        if any(line_suppresses(text, _CHU009) for text in suppress_lines):
            return
        seen_lines.add(report_line)
        statement_kind = "return" if isinstance(kind_node, ast.Return) else "pass"
        findings.append(
            Finding(
                path=filepath,
                line=report_line,
                code=_CHU009,
                message=(
                    f"silent ``{statement_kind}`` in test body: runner "
                    f"reports the test as PASS without exercising the "
                    f"assertions below.  Use "
                    f"``chumicro_test_harness.skip(reason)`` for a visible "
                    f"skip, or ``raise AssertionError(...)`` if reaching this "
                    f"line is a bug."
                ),
            )
        )

    for node in _ifs_in_scope(func):
        if node.body:
            last = node.body[-1]
            if isinstance(last, ast.Return | ast.Pass):
                _emit(
                    node.lineno,
                    (
                        _source_line(source_lines, node.lineno),
                        _source_line(source_lines, last.lineno),
                    ),
                    last,
                )
        # A real ``else:`` body is the canonical "skip when the hardware
        # is missing" shape.  An ``elif`` is a lone nested ``ast.If`` in
        # orelse that _ifs_in_scope yields on its own, so skip it here.
        orelse = node.orelse
        if orelse and not (len(orelse) == 1 and isinstance(orelse[0], ast.If)):
            last_else = orelse[-1]
            if isinstance(last_else, ast.Return | ast.Pass):
                _emit(
                    last_else.lineno,
                    (_source_line(source_lines, last_else.lineno),),
                    last_else,
                )

    for compound_body in _return_bodies_in_scope(func):
        last = compound_body[-1] if compound_body else None
        if isinstance(last, ast.Return):
            _emit(last.lineno, (_source_line(source_lines, last.lineno),), last)

    body = func.body
    for index, stmt in enumerate(body):
        if index == len(body) - 1:
            # Final statement deliberately not flagged: a trailing
            # return/pass after the asserts ran is harmless, and an
            # assertionless test ending in pass is caught by CHU010.
            continue
        if isinstance(stmt, ast.Return | ast.Pass):
            _emit(stmt.lineno, (_source_line(source_lines, stmt.lineno),), stmt)

    findings.sort(key=lambda finding: finding.line)
    return findings


def _no_assertion_findings(
    func: ast.FunctionDef, filepath: Path, source_lines: list[str]
) -> list[Finding]:
    if _function_has_assertion(func):
        return []
    header_line = source_lines[func.lineno - 1] if func.lineno <= len(source_lines) else ""
    if line_suppresses(header_line, _CHU010):
        return []
    return [
        Finding(
            path=filepath,
            line=func.lineno,
            code=_CHU010,
            message=(
                f"test function {func.name!r} has no assertion; pass an "
                f"explicit ``assert``, ``raise``, ``pytest.raises``, or "
                f"``chumicro_test_harness.skip`` so the test can fail on a "
                f"regression."
            ),
        )
    ]


def _check_file_for_code(
    filepath: Path,
    repo_root: Path,
    code: str,
) -> list[Finding]:
    if not _is_in_scope(filepath, repo_root):
        return []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, code)
    if tree is None:
        return syntax_findings

    source_lines = text.splitlines()
    findings: list[Finding] = []
    for func in _iter_test_functions(tree):
        if code == _CHU009:
            findings.extend(_silent_return_findings(func, filepath, source_lines))
        elif code == _CHU010:
            findings.extend(_no_assertion_findings(func, filepath, source_lines))
    return findings


class _LibraryTestRule(Rule):
    """Common scaffolding for CHU009 + CHU010."""

    def __init__(self, *, code: str, description: str) -> None:
        self.code = code
        self.description = description

    def check(self, repo_root: Path) -> list[Finding]:
        roots = _scan_libraries(repo_root)
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            for filepath in iter_text_files(root, suffixes=(".py",)):
                findings.extend(_check_file_for_code(filepath, repo_root, self.code))
        return findings


CHU009 = _LibraryTestRule(
    code=_CHU009,
    description="no silent ``if <cond>: return/pass`` in library test bodies",
)

CHU010 = _LibraryTestRule(
    code=_CHU010,
    description="library test functions must contain at least one assertion",
)
