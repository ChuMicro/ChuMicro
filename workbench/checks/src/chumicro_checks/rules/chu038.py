"""CHU038: library examples and demo apps never exit.

A board runs its ``code.py`` until the power goes, and the first
programs a hobbyist meets on Adafruit Learn or in the Arduino IDE end
in a loop that never returns.  An example that ends its own program
leaves that reader at a REPL prompt with nothing moving, unable to tell
a finished program from a crashed one.  So every example and demo ends
in a visible module-level ``while True:`` that keeps doing the work the
file teaches.

Scope: ``libraries/<name>/examples/*.py`` (``helpers.py`` excluded: it
is a support module the examples import, not a program) and
``demos/<name>/app.py``.  Files in subdirectories of ``examples/`` are
not walked.  Absent both trees, a silent no-op.

Flags, via AST:

* A call that ends the program, anywhere in the file: ``raise
  SystemExit`` (bare or called), ``sys.exit(...)``, ``os._exit(...)``,
  and bare ``exit(...)`` / ``quit(...)``.
* A file that never reaches a loop that runs forever.  The rule wants a
  ``while`` whose test is a true constant (``while True:`` or
  ``while 1:``) and whose body holds no ``break`` that leaves it.  The
  loop may sit inside a module-level ``if`` / ``try`` / ``with``, but
  never inside a ``def`` or ``class``: a loop wrapped in ``main()`` is a
  loop the reader has to go and find.  A ``while not done:`` at module
  level is not enough, because the program runs off the end once
  ``done`` turns true.  The finding points at line 1.

Suppression:

* ``# noqa: CHU038`` on an exit call's line mutes that call.
* A comment-only line naming the code, such as
  ``# noqa: CHU038 - benchmark: runs every scenario once, then prints a
  summary``, exempts the whole file.  It is the declaration for a script
  that runs once by design, written where the reader of that file sees
  it.  A bare ``# noqa`` line does not exempt a file.
"""

from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Iterable, Iterator
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU038"

#: Example files that are support modules rather than programs.
_NOT_PROGRAMS: frozenset[str] = frozenset({"helpers.py"})

#: Bare builtin names whose call ends the program.
_EXIT_BUILTINS: frozenset[str] = frozenset({"exit", "quit"})

#: ``(module, attribute)`` pairs whose call ends the program.
_EXIT_ATTRIBUTES: frozenset[tuple[str, str]] = frozenset({
    ("sys", "exit"),
    ("os", "_exit"),
})

#: Statements whose bodies run in a scope of their own, so a loop or a
#: ``break`` inside them does not belong to the enclosing code.
_SCOPE_STATEMENTS: tuple[type[ast.stmt], ...] = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)

#: Loops whose body owns any ``break`` written inside it.
_LOOP_STATEMENTS: tuple[type[ast.stmt], ...] = (ast.For, ast.AsyncFor, ast.While)


def _program_files(repo_root: Path) -> list[Path]:
    """Return every example and demo program under *repo_root*, sorted.

    The list is each ``libraries/<name>/examples/*.py`` other than
    ``helpers.py``, followed by each ``demos/<name>/app.py``.
    """
    programs: list[Path] = []
    libraries_dir = repo_root / "libraries"
    if libraries_dir.is_dir():
        for examples_dir in sorted(libraries_dir.glob("*/examples")):
            for filepath in sorted(examples_dir.glob("*.py")):
                if filepath.is_file() and filepath.name not in _NOT_PROGRAMS:
                    programs.append(filepath)
    demos_dir = repo_root / "demos"
    if demos_dir.is_dir():
        for filepath in sorted(demos_dir.glob("*/app.py")):
            if filepath.is_file():
                programs.append(filepath)
    return programs


def _nested_statement_lists(statement: ast.stmt) -> Iterator[list[ast.stmt]]:
    """Yield each statement list nested one level inside *statement*.

    Covers ``body`` / ``orelse`` / ``finalbody`` plus the bodies of
    ``except`` handlers and ``match`` cases.
    """
    for field_name in ("body", "orelse", "finalbody"):
        nested = getattr(statement, field_name, None)
        if isinstance(nested, list) and nested and isinstance(nested[0], ast.stmt):
            yield nested
    for handler in getattr(statement, "handlers", ()):
        yield handler.body
    for case in getattr(statement, "cases", ()):
        yield case.body


def _module_level_whiles(statements: Iterable[ast.stmt]) -> Iterator[ast.While]:
    """Yield every ``while`` in *statements* outside any ``def`` or ``class``."""
    for statement in statements:
        if isinstance(statement, _SCOPE_STATEMENTS):
            continue
        if isinstance(statement, ast.While):
            yield statement
        for nested in _nested_statement_lists(statement):
            yield from _module_level_whiles(nested)


def _breaks_out(statements: Iterable[ast.stmt]) -> bool:
    """Return whether a ``break`` in *statements* leaves the enclosing loop.

    A ``break`` inside a nested loop's body ends that nested loop, so
    only the nested loop's ``else`` clause is searched.  Function and
    class bodies are skipped: a ``break`` there cannot reach the loop.
    """
    for statement in statements:
        if isinstance(statement, ast.Break):
            return True
        if isinstance(statement, _SCOPE_STATEMENTS):
            continue
        if isinstance(statement, _LOOP_STATEMENTS):
            if _breaks_out(statement.orelse):
                return True
            continue
        for nested in _nested_statement_lists(statement):
            if _breaks_out(nested):
                return True
    return False


def _runs_forever(loop: ast.While) -> bool:
    """Return whether *loop* tests a true constant and has no ``break``."""
    test = loop.test
    always_true = (
        isinstance(test, ast.Constant)
        and isinstance(test.value, int)
        and bool(test.value)
    )
    return always_true and not _breaks_out(loop.body)


def _exit_call(node: ast.AST) -> str | None:
    """Return a label for *node* when it ends the program, else ``None``."""
    if isinstance(node, ast.Raise) and node.exc is not None:
        raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if isinstance(raised, ast.Name) and raised.id == "SystemExit":
            return "raise SystemExit"
        return None
    if not isinstance(node, ast.Call):
        return None
    called = node.func
    if isinstance(called, ast.Name) and called.id in _EXIT_BUILTINS:
        return f"{called.id}()"
    if (
        isinstance(called, ast.Attribute)
        and isinstance(called.value, ast.Name)
        and (called.value.id, called.attr) in _EXIT_ATTRIBUTES
    ):
        return f"{called.value.id}.{called.attr}()"
    return None


def _file_exempt(text: str) -> bool:
    """Return whether *text* carries a comment-only ``# noqa: CHU038`` line.

    Only a real comment token counts, so the directive quoted inside a
    docstring exempts nothing, and the code must be named: a bare
    ``# noqa`` line is too broad to excuse a whole program.  *text* has
    already parsed as Python, so tokenizing it cannot fail.
    """
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type != tokenize.COMMENT:
            continue
        if token.line[: token.start[1]].strip():
            continue
        if _RULE_CODE in token.string and line_suppresses(token.string, _RULE_CODE):
            return True
    return False


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings
    if _file_exempt(text):
        return []
    source_lines = text.splitlines()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        what = _exit_call(node)
        if what is None:
            continue
        if line_suppresses(source_lines[node.lineno - 1], _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=node.lineno,
                code=_RULE_CODE,
                message=(
                    f"{what} ends the program; print what went wrong and "
                    f"retry on the next pass of the loop instead"
                ),
            )
        )
    if not any(_runs_forever(loop) for loop in _module_level_whiles(tree.body)):
        findings.append(
            Finding(
                path=filepath,
                line=1,
                code=_RULE_CODE,
                message=(
                    "no module-level `while True:` loop without a `break`; end "
                    "the file in one that keeps repeating the work it teaches"
                ),
            )
        )
    findings.sort(key=lambda finding: finding.line)
    return findings


class CHU038_ExamplesNeverExit(Rule):
    code = _RULE_CODE
    description = (
        "examples and demo apps never exit: end in a module-level "
        "`while True:` loop"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for filepath in _program_files(repo_root):
            findings.extend(_check_file(filepath))
        return findings


CHU038 = CHU038_ExamplesNeverExit()
