"""Lint for silent-pass / silent-skip patterns in test bodies.

Any new test that introduces one of the offending shapes fails CI
(or the local ``run.py lint`` check) before it can land.

Two rules.

CHU009 — no bare ``return`` / ``pass`` from a test body:

    def test_thing() -> None:
        if not _PRECONDITION:
            return            # silent PASS — runner reports as PASS

The lightweight test_harness runner (``support/test_harness/runner.py``)
reports any test that returns without raising as PASS, and pytest
does the same.  A ``return`` from a guard means the assertions below
never ran but the test reports green.  Use
``chumicro_test_harness.skip(reason)`` (or ``raise AssertionError(...)``
for "shouldn't have been reached" cases) instead.

CHU010 — a test function must contain at least one assertion:

    def test_close_idempotent():
        sock.close()
        sock.close()       # no assertion — passes regardless of behavior

Without an explicit ``assert``, ``raise``, ``pytest.fail``,
``pytest.raises``, ``chumicro_test_harness.skip``, etc., the only
way the test fails is a crash inside the body.  Idempotency tests
should at minimum check post-state ("``assert sock.fileno() == -1``"
after a double-close).

Scope: ``libraries/*/tests/`` and ``libraries/*/functional_tests/``.
Workbench tests are out of scope (the audit was library-focused);
they can be added later by extending :data:`_SCOPE_DIRECTORIES`.

Suppression: ``# noqa: CHU009`` or ``# noqa: CHU010`` on the
flagged line.  Use sparingly — most violations are real silent-skip
bugs.

Usage::

    python scripts/check_no_silent_test_skip.py
    python scripts/check_no_silent_test_skip.py [paths...]
    python scripts/run.py lint            # runs automatically alongside ruff
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from repo_layout import ROOT, discover_ruff_paths

_CHU009 = "CHU009"
_CHU010 = "CHU010"

#: Directories under each library where these rules apply.  The
#: pattern lives in ``tests/`` (cross-runtime + pytest-only suites)
#: and ``functional_tests/`` (on-device suites).
_SCOPE_DIRECTORIES = ("tests", "functional_tests")

#: Function-call names that count as a real assertion.  The rightmost
#: dotted segment is checked, so ``pytest.skip`` and ``skip``,
#: ``pytest.raises`` and ``raises``, etc. all match.
_ASSERTION_CALL_NAMES = frozenset({
    "fail",          # pytest.fail / chumicro_test_harness.fail
    "skip",          # pytest.skip / chumicro_test_harness.skip
    "skip_module",
    "raises",        # pytest.raises / chumicro_test_harness.raises
    "importorskip",  # pytest.importorskip — declares a runtime gate
    "AssertionError",
})

# Constructed dynamically so ruff doesn't interpret these as directives.
_NOQA_TAG = "# " + "noqa"


def _read_noqa_lines(source: str, rule_code: str) -> set[int]:
    """Return the set of 1-based line numbers that suppress *rule_code*.

    Args:
        source: Full file source text.
        rule_code: The CHU code to look for (``CHU009`` or ``CHU010``).
    """
    suppressed: set[int] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        tag_pos = line.find(_NOQA_TAG)
        if tag_pos == -1:
            continue
        after = line[tag_pos + len(_NOQA_TAG):]
        if after.strip() == "" or rule_code in after:
            suppressed.add(line_number)
    return suppressed


def _is_in_scope(filepath: Path) -> bool:
    """Return whether the file should be linted by these rules.

    Only ``libraries/<name>/tests/test_*.py`` and
    ``libraries/<name>/functional_tests/test_*.py`` are in scope.

    Args:
        filepath: Path to inspect.
    """
    if filepath.suffix != ".py":
        return False
    if not filepath.name.startswith("test_"):
        return False
    parts = filepath.parts
    if "libraries" not in parts:
        return False
    library_index = parts.index("libraries")
    # Need at least: libraries/<name>/<scope_dir>/test_*.py
    if library_index + 2 >= len(parts):
        return False
    return parts[library_index + 2] in _SCOPE_DIRECTORIES


def _iter_test_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Yield every ``def test_*`` function in the module.

    Includes module-level ``def test_*`` and methods on ``Test*``
    classes (mirroring pytest's collection rules).

    Args:
        tree: Parsed AST of the file.
    """
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


def _has_assertion(func: ast.FunctionDef) -> bool:
    """Return whether *func*'s body contains anything that can fail it.

    "Can fail" means at least one of: ``assert ...``, ``raise ...``,
    a call to one of :data:`_ASSERTION_CALL_NAMES` (e.g. ``skip``,
    ``raises``, ``fail``), or a ``with raises(...)`` block.  An
    empty test or one whose body is purely setup + side-effecting
    calls fails the check.
    """
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            name = _callable_tail_name(node.func)
            if name in _ASSERTION_CALL_NAMES:
                return True
    return False


def _callable_tail_name(node: ast.expr) -> str | None:
    """Return the rightmost dotted segment of a call's callable.

    Examples:

        ``foo`` → ``"foo"``
        ``module.foo`` → ``"foo"``
        ``a.b.c.foo`` → ``"foo"``

    Anything more exotic (a subscript callable, a lambda, etc.) returns
    ``None`` — the call is treated as not-an-assertion, conservative.

    Args:
        node: The ``func`` slot from an ``ast.Call``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _flag_silent_returns(
    func: ast.FunctionDef, noqa_009: set[int],
) -> list[tuple[int, str]]:
    """Find ``if <cond>: return/pass`` patterns inside *func*.

    Walks the entire function body — late guards count too,
    matching the semantics of the rule (any return that lets a test
    pass without exercising its assertions is silent-PASS).

    Args:
        func: A test function node.
        noqa_009: Line numbers that suppress CHU009.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        body = node.body
        if len(body) != 1:
            continue
        first = body[0]
        if not isinstance(first, (ast.Return, ast.Pass)):
            continue
        if first.lineno in noqa_009 or node.lineno in noqa_009:
            continue
        statement_kind = "return" if isinstance(first, ast.Return) else "pass"
        hits.append((
            node.lineno,
            f"silent ``if <cond>: {statement_kind}`` in test body — "
            f"runner reports the test as PASS without exercising the "
            f"assertions below.  Use "
            f"``chumicro_test_harness.skip(reason)`` for a visible "
            f"skip, or ``raise AssertionError(...)`` if reaching this "
            f"line is a bug.",
        ))
    return hits


def check_file(filepath: Path, source: str | None = None) -> list[str]:
    """Check a single file for CHU009 / CHU010 violations.

    Args:
        filepath: Path to the Python file.
        source: Optional pre-read source text.
    """
    if not _is_in_scope(filepath):
        return []

    text = source if source is not None else filepath.read_text(encoding="utf-8")

    try:
        tree = ast.parse(text, filename=str(filepath))
    except SyntaxError:
        return []

    noqa_009 = _read_noqa_lines(text, _CHU009)
    noqa_010 = _read_noqa_lines(text, _CHU010)

    relative = filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    errors: list[str] = []

    for func in _iter_test_functions(tree):
        for lineno, message in _flag_silent_returns(func, noqa_009):
            errors.append(f"{relative}:{lineno}: {_CHU009} {message}")

        if not _has_assertion(func) and func.lineno not in noqa_010:
            errors.append(
                f"{relative}:{func.lineno}: {_CHU010} test function "
                f"{func.name!r} has no assertion — pass an explicit "
                f"``assert``, ``raise``, ``pytest.raises``, or "
                f"``chumicro_test_harness.skip`` so the test can fail "
                f"on a regression.",
            )

    return errors


def check_paths(paths: list[str]) -> int:
    """Check all .py files under *paths*.

    Args:
        paths: Directories or files to scan.
    """
    all_errors: list[str] = []

    for path_str in paths:
        path = Path(path_str)
        if path.is_file():
            all_errors.extend(check_file(path))
        elif path.is_dir():
            for py_file in sorted(path.rglob("test_*.py")):
                parts = py_file.relative_to(path).parts
                if any(part in ("__pycache__", "site") for part in parts):
                    continue
                all_errors.extend(check_file(py_file))

    if all_errors:
        for error in all_errors:
            print(error)
        print(
            f"\nFound {len(all_errors)} silent-test-skip violation(s).",
        )
        print(
            "A test that returns/passes without an assertion is "
            "reported as PASS — that hides regressions.",
        )
        print(
            f"Fix: rewrite the test body, or add "
            f"'# noqa: {_CHU009}' / '# noqa: {_CHU010}' on the "
            f"flagged line for genuine exceptions.",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Paths to check.  Defaults to the same paths ruff scans.
    """
    paths = argv if argv else [str(path) for path in discover_ruff_paths()]
    return check_paths(paths)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
