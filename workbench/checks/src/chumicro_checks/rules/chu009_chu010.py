"""CHU009 + CHU010 — no silent-pass / no-assertion patterns in test bodies.

Two paired rules, both targeting library-side test files
(``libraries/<name>/tests/test_*.py`` and
``libraries/<name>/functional_tests/test_*.py``).  They share scope
detection and AST walking but emit distinct findings under distinct
codes.

CHU009 — no bare ``return`` / ``pass`` from a test body::

    def test_thing() -> None:
        if not _PRECONDITION:
            return            # silent PASS — runner reports as PASS

The test_harness runner reports any test that returns without
raising as PASS, and pytest does the same.  Use
``chumicro_test_harness.skip(reason)`` (or ``raise AssertionError(...)``
for "shouldn't have been reached" cases) instead.

CHU010 — a test function must contain at least one assertion::

    def test_close_idempotent():
        sock.close()
        sock.close()       # no assertion — passes regardless of behavior

Without an explicit ``assert``, ``raise``, ``pytest.fail``,
``pytest.raises``, ``chumicro_test_harness.skip``, etc., the only
way the test fails is a crash inside the body.

Self-scope: only files under ``libraries/<pkg>/tests/`` or
``libraries/<pkg>/functional_tests/`` matching ``test_*.py`` are
checked.  In a tree without a ``libraries/`` directory, both rules
return no findings — silent no-op.

Suppression: ``# noqa: CHU009`` / ``# noqa: CHU010`` on the
flagged line (or on the function header for CHU010).
"""

from __future__ import annotations

import ast
from pathlib import Path

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
    """Return the libraries/ tree if it exists; else empty list."""
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
    """Return whether *func*'s body contains anything that can fail it."""
    for node in ast.walk(func):
        if isinstance(node, ast.Assert | ast.Raise):
            return True
        if isinstance(node, ast.Call):
            name = _callable_tail_name(node.func)
            if name in _ASSERTION_CALL_NAMES:
                return True
    return False


def _silent_return_findings(
    func: ast.FunctionDef, filepath: Path, source_lines: list[str]
) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        body = node.body
        if len(body) != 1:
            continue
        first = body[0]
        if not isinstance(first, ast.Return | ast.Pass):
            continue
        if_line = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
        body_line = (
            source_lines[first.lineno - 1] if first.lineno <= len(source_lines) else ""
        )
        if line_suppresses(if_line, _CHU009) or line_suppresses(body_line, _CHU009):
            continue
        statement_kind = "return" if isinstance(first, ast.Return) else "pass"
        findings.append(
            Finding(
                path=filepath,
                line=node.lineno,
                code=_CHU009,
                message=(
                    f"silent ``if <cond>: {statement_kind}`` in test body — "
                    f"runner reports the test as PASS without exercising the "
                    f"assertions below.  Use "
                    f"``chumicro_test_harness.skip(reason)`` for a visible "
                    f"skip, or ``raise AssertionError(...)`` if reaching this "
                    f"line is a bug."
                ),
            )
        )
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
                f"test function {func.name!r} has no assertion — pass an "
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
    try:
        tree = ast.parse(text, filename=str(filepath))
    except SyntaxError:
        return []

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
