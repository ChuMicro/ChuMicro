"""Lint for single-letter variable names and banned abbreviations (Decision 0022).

Walks Python files and flags single-letter variable names and specific
short abbreviations that should be spelled out.  The only allowed
single-letter name is ``_`` (throwaway / unused binding), plus
single-letter names used as ``for``-loop targets are permitted.

Suppression: add ``# noqa: CHU001`` on the flagged line.

Usage::

    python scripts/check_names.py [paths...]
    python scripts/run.py lint         # runs automatically alongside ruff
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from repo_layout import ROOT, discover_ruff_paths

_RULE_CODE = "CHU001"
_ALLOWED = {"_"}
_BANNED = {"env", "buf", "src", "cmd", "msg", "err", "ref", "addr", "exc", "exec"}
_BANNED_SUFFIXES = tuple(f"_{word}" for word in _BANNED)
# Constructed dynamically so ruff doesn't interpret it as a directive.
_NOQA_TAG = "# " + "noqa"


def _read_noqa_lines(source: str) -> set[int]:
    """Return the set of 1-based line numbers that suppress CHU001.

    Args:
        source: Full file source text.
    """
    suppressed: set[int] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        tag_pos = line.find(_NOQA_TAG)
        if tag_pos == -1:
            continue
        # Everything after the noqa tag — empty means bare suppression.
        after = line[tag_pos + len(_NOQA_TAG):]
        if after.strip() == "" or _RULE_CODE in after:
            suppressed.add(line_number)
    return suppressed


def _for_loop_target_ids(tree: ast.Module) -> set[tuple[int, str]]:
    """Return ``(line, name)`` pairs for all ``for``-loop target variables.

    Handles simple targets (``for i in ...``) and tuple-unpacking
    targets (``for i, j in ...``).

    Args:
        tree: Parsed AST of the file.
    """
    result: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            target = node.target
            if isinstance(target, ast.Name):
                result.add((target.lineno, target.id))
            elif isinstance(target, ast.Tuple):
                for element in target.elts:
                    if isinstance(element, ast.Name):
                        result.add((element.lineno, element.id))
    return result


def _collect_names(tree: ast.Module) -> list[tuple[int, str, str]]:
    """Walk the AST and collect all flagged binding names.

    Returns a list of ``(line_number, name, reason)`` tuples.

    Args:
        tree: Parsed AST of the file.
    """
    hits: list[tuple[int, str, str]] = []
    loop_targets = _for_loop_target_ids(tree)

    for node in ast.walk(tree):
        targets: list[tuple[int, str]] = []

        # Assignments: x = ...
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            targets.append((node.lineno, node.id))

        # Function / method parameters
        elif isinstance(node, ast.arg):
            targets.append((node.lineno, node.arg))

        # Exception handlers: except ... as e
        elif isinstance(node, ast.ExceptHandler) and node.name:
            targets.append((node.lineno, node.name))

        # Function / method names
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            targets.append((node.lineno, node.name))

        for lineno, name in targets:
            if len(name) == 1 and name not in _ALLOWED:
                # Allow single-letter names in for-loop targets.
                if (lineno, name) in loop_targets:
                    continue
                hits.append((lineno, name, "single-letter name"))
            elif name in _BANNED:
                hits.append((lineno, name, "banned abbreviation"))
            elif name.endswith(_BANNED_SUFFIXES):
                suffix = name.rsplit("_", 1)[-1]
                hits.append((lineno, name, f"banned abbreviation suffix '_{suffix}'"))

    return hits


def check_file(filepath: Path, source: str | None = None) -> list[str]:
    """Check a single file for flagged names.

    Args:
        filepath: Path to the Python file.
        source: Optional pre-read source text.

    Returns:
        List of formatted error strings (empty if clean).
    """
    text = source if source is not None else filepath.read_text(encoding="utf-8")

    try:
        tree = ast.parse(text, filename=str(filepath))
    except SyntaxError:
        return []

    noqa_lines = _read_noqa_lines(text)
    errors: list[str] = []

    for lineno, name, reason in _collect_names(tree):
        if lineno in noqa_lines:
            continue
        relative = filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
        errors.append(f"{relative}:{lineno}: {_RULE_CODE} {reason} '{name}'")

    return errors


def check_paths(paths: list[str]) -> int:
    """Check all .py files under the given paths.

    Args:
        paths: Directories or files to scan.

    Returns:
        Exit code (0 for clean, 1 for violations found).
    """
    all_errors: list[str] = []

    for path_str in paths:
        path = Path(path_str)
        if path.is_file() and path.suffix == ".py":
            all_errors.extend(check_file(path))
        elif path.is_dir():
            for py_file in sorted(path.rglob("*.py")):
                # Skip __pycache__ and site/ directories
                parts = py_file.relative_to(path).parts
                if any(part in ("__pycache__", "site") for part in parts):
                    continue
                all_errors.extend(check_file(py_file))

    if all_errors:
        for error in all_errors:
            print(error)
        print(f"\nFound {len(all_errors)} naming violation(s).")
        print("Spell out abbreviations for readability — code is read more than written.")
        print(f"Fix: rename them, or add '# noqa: {_RULE_CODE}' to suppress.")
        print("Why: plans/decisions/0022-naming-conventions.md")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Paths to check. Defaults to the same paths ruff scans.
    """
    paths = argv if argv else [str(path) for path in discover_ruff_paths()]
    return check_paths(paths)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
