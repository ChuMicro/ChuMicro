"""CHU015: module-docstring capability claims vs shipped symbols.

A module docstring that calls a capability "future work" / "not yet
implemented" / "planned" while that capability ships as a public
symbol in the same module is the drift class this rule catches.  The
shape: a docstring says feature X is planned, the module exports a
function or class implementing X.  Either the docstring is stale or
the symbol is unintentional public surface. Both are leaks of stale
docs to a PyPI consumer reading the shipped source.  Prose lockstep
doesn't catch it. This rule does.

Mechanism (deterministic, clause-scoped to keep false positives low):

* The module docstring is split into clauses on ``.``, ``;`` and
  blank lines.
* A clause containing a *not-yet predicate* (``future work``,
  ``not yet implemented``, ``planned``, ``TODO``/``FIXME``,
  ``coming soon``, ``unimplemented``, ``is a stub``, ``will be
  added/implemented/supported``) is checked for a whole-word,
  case-insensitive match against the module's **public defined
  symbols**, meaning top-level ``def`` / ``class`` names and public
  methods of top-level classes.
* A match means the docstring disclaims something the module
  actually ships → finding.

Clause scoping is the false-positive guard: ``the from_config
constructor is the entry point; raw socket injection is planned``
does not flag ``from_config`` because the ``;`` ends its clause
before ``planned``.

Scope: ``libraries/<pkg>/src/`` only.  Tests, examples, workbench,
and scripts are out of scope.  Absent ``libraries/``, a silent no-op.

Suppression: ``# noqa: CHU015`` on the offending docstring line (for
the legitimately-exceptional case, e.g. a same-named symbol that is
genuinely an unrelated stub).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU015"

#: Phrases that disclaim a capability as not-shipped.  Kept
#: high-signal. ``not supported`` alone is excluded because it is
#: overloaded with legitimate per-runtime platform caveats.
_NOT_YET = re.compile(
    r"future work"
    r"|not yet (?:implemented|supported|available|done|wired)"
    r"|\bunimplemented\b"
    r"|\bTODO\b|\bFIXME\b"
    r"|coming soon"
    r"|\bis a stub\b|\bare stubs\b"
    r"|\bplanned\b"
    r"|will be (?:added|implemented|supported|wired)",
    re.IGNORECASE,
)

#: Clause boundaries inside a docstring.
_CLAUSE_SPLIT = re.compile(r"[.;\n]")


def _is_in_library_source(filepath: Path, repo_root: Path) -> bool:
    if filepath.suffix != ".py":
        return False
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return False
    parts = relative.parts
    return len(parts) >= 3 and parts[0] == "libraries" and parts[2] == "src"


def _public_symbols(tree: ast.Module) -> set[str]:
    """Public top-level def/class names + public methods of top classes."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                names.add(node.name)
            for child in node.body:
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and not child.name.startswith("_"):
                    names.add(child.name)
    return names


def _module_docstring_node(tree: ast.Module) -> ast.Constant | None:
    if not tree.body:
        return None
    first = tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.value
    return None


def _offending_symbols(docstring: str, symbols: set[str]) -> set[str]:
    """Public symbols named in a not-yet clause of *docstring*."""
    hits: set[str] = set()
    for clause in _CLAUSE_SPLIT.split(docstring):
        if not _NOT_YET.search(clause):
            continue
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", clause.lower()))
        for symbol in symbols:
            if symbol.lower() in words:
                hits.add(symbol)
    return hits


def _phrase_line(
    source_lines: list[str], doc_node: ast.Constant,
) -> int:
    """Best-effort source line of the first not-yet phrase in the docstring.

    Falls back to the docstring's start line when the phrase spans a
    boundary the line scan can't see.
    """
    start = doc_node.lineno
    end = getattr(doc_node, "end_lineno", start) or start
    for index in range(start - 1, min(end, len(source_lines))):
        if _NOT_YET.search(source_lines[index]):
            return index + 1
    return start


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
    doc_node = _module_docstring_node(tree)
    if doc_node is None:
        return []
    docstring = doc_node.value
    if not _NOT_YET.search(docstring):
        return []
    offending = _offending_symbols(docstring, _public_symbols(tree))
    if not offending:
        return []
    source_lines = text.splitlines()
    line = _phrase_line(source_lines, doc_node)
    if line - 1 < len(source_lines) and line_suppresses(
        source_lines[line - 1], _RULE_CODE,
    ):
        return []
    named = ", ".join(sorted(offending))
    return [
        Finding(
            path=filepath,
            line=line,
            code=_RULE_CODE,
            message=(
                f"module docstring disclaims {named!r} as future work / "
                f"not-yet-implemented, but it ships as a public symbol in "
                f"this module; update the docstring to the real surface "
                f"(or # noqa: CHU015 if the symbol is genuinely an "
                f"unrelated stub)"
            ),
        )
    ]


class CHU015_DocstringCapabilityDrift(Rule):
    code = _RULE_CODE
    description = (
        "module-docstring 'future work' claims must match shipped symbols"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        libraries_dir = repo_root / "libraries"
        if not libraries_dir.is_dir():
            return []
        findings: list[Finding] = []
        for filepath in iter_text_files(libraries_dir, suffixes=(".py",)):
            findings.extend(_check_file(filepath, repo_root))
        return findings


CHU015 = CHU015_DocstringCapabilityDrift()
