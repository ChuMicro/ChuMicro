"""CHU001: descriptive names. No single-letter or banned-abbreviation bindings.

Walks every ``.py`` file under the configured top-level directories
and flags:

* Single-letter variable names (except ``_``).  Loop and
  comprehension targets are exempt: ``for i in range(n):`` and
  ``sum(x for x in values)`` are allowed for human contributors.
  Agent-generated code is expected to use descriptive loop targets too,
  but the exception lives in the rule for compatibility.
* Banned bare abbreviations: ``env``, ``buf``, ``src``, ``cmd``,
  ``msg``, ``err``, ``ref``, ``addr``, ``exc``, ``exec``.
* Banned-suffix names: anything ending in ``_<abbrev>`` from the same
  set (``foo_src``, ``cmd_buf``, etc.).

Bindings inspected: assignment targets, function parameters,
``except`` names, function / class names, and ``import ... as`` aliases
(``import struct as s`` is a single-letter binding just like ``s =
struct``).

Self-scope: scans top-level directories under the repo root.  In a
tree without those (a downstream user workspace), the rule returns
no findings, a silent no-op.

Suppression: ``# noqa: CHU001`` on the offending line.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU001"

_ALLOWED_SINGLE_LETTER = frozenset({"_"})

_BANNED_ABBREVIATIONS = frozenset({
    "env", "buf", "src", "cmd", "msg",
    "err", "ref", "addr", "exc", "exec",
})

_BANNED_SUFFIXES = tuple(f"_{word}" for word in _BANNED_ABBREVIATIONS)

_SCAN_TOP_LEVELS = (
    # Mono-repo shape.
    "libraries", "workbench", "support", "scripts",
    # Template / workspace shape.
    "packages", "projects", "shared", "examples", "tests",
)


def _scan_roots(repo_root: Path) -> list[Path]:
    """Return the directory roots to walk under *repo_root*."""
    roots: list[Path] = []
    for top_level in _SCAN_TOP_LEVELS:
        candidate = repo_root / top_level
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _target_names(target: ast.expr) -> set[tuple[int, str]]:
    """Return ``(line, name)`` for every ``Name`` bound by *target*.

    Descends nested tuple / list unpacking and unwraps starred
    elements, so ``for a, (b, *rest) in pairs`` yields all four names.
    """
    names: set[tuple[int, str]] = set()
    if isinstance(target, ast.Name):
        names.add((target.lineno, target.id))
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            names |= _target_names(element)
    elif isinstance(target, ast.Starred):
        names |= _target_names(target.value)
    return names


def _loop_target_ids(tree: ast.Module) -> set[tuple[int, str]]:
    """Return ``(line, name)`` pairs for every loop / comprehension target.

    Covers ``for`` and ``async for`` statements and the ``for`` clause
    of every comprehension or generator expression.  These bindings are
    exempt from the single-letter rule the same way ``for i in
    range(n):`` is: a single-letter comprehension variable
    (``sum(x for x in values)``) is idiomatic, not a violation.
    """
    result: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            result |= _target_names(node.target)
        elif isinstance(node, ast.comprehension):
            result |= _target_names(node.target)
    return result


def _collect_hits(tree: ast.Module) -> list[tuple[int, str, str]]:
    """Return ``(line, name, reason)`` triples for every flagged binding."""
    hits: list[tuple[int, str, str]] = []
    loop_targets = _loop_target_ids(tree)

    for node in ast.walk(tree):
        targets: list[tuple[int, str]] = []

        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            targets.append((node.lineno, node.id))
        elif isinstance(node, ast.arg):
            targets.append((node.lineno, node.arg))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            targets.append((node.lineno, node.name))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            targets.append((node.lineno, node.name))
        elif isinstance(node, ast.ClassDef):
            targets.append((node.lineno, node.name))
        elif isinstance(node, ast.alias) and node.asname:
            targets.append((node.lineno, node.asname))

        for lineno, name in targets:
            if len(name) == 1 and name not in _ALLOWED_SINGLE_LETTER:
                if (lineno, name) in loop_targets:
                    continue
                hits.append((lineno, name, "single-letter name"))
            elif name in _BANNED_ABBREVIATIONS:
                hits.append((lineno, name, "banned abbreviation"))
            elif name.endswith(_BANNED_SUFFIXES):
                suffix = name.rsplit("_", 1)[-1]
                hits.append((lineno, name, f"banned abbreviation suffix '_{suffix}'"))

    return hits


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings

    source_lines = text.splitlines()
    findings: list[Finding] = []
    for lineno, name, reason in _collect_hits(tree):
        line_text = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
        if line_suppresses(line_text, _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=lineno,
                code=_RULE_CODE,
                message=f"{reason} '{name}'",
            )
        )
    return findings


class CHU001_DescriptiveNames(Rule):
    code = _RULE_CODE
    description = (
        "no single-letter variable names; no bare or suffixed banned "
        "abbreviations (env, buf, src, cmd, msg, err, ref, addr, exc, exec)"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        roots = _scan_roots(repo_root)
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            for filepath in iter_text_files(root, suffixes=(".py",)):
                findings.extend(_check_file(filepath))
        return findings


CHU001 = CHU001_DescriptiveNames()
