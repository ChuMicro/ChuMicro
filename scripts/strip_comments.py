"""Strip docstrings and non-lint-exception comments from Python source.

Produces a clean-slate baseline that a comment writer can write fresh
docstrings against, with no prompt influence from the original prose.

Rules:

* Removes module / class / function docstrings (the first ``Expr`` whose
  value is a string constant on ``Module`` / ``ClassDef`` /
  ``FunctionDef`` / ``AsyncFunctionDef`` bodies).
* Removes ``#`` comments EXCEPT lint-exception annotations:
  ``# noqa``, ``# type: ignore``, ``# pylint: disable``,
  ``# pragma: no cover``, ``# mypy:``, ``# ruff:``.
* When a class or function body becomes empty after stripping its
  docstring, inserts ``pass`` so the result still parses.  Empty
  ``Module`` bodies are left empty (legal Python).
* Preserves leading whitespace exactly per line (tab / space convention
  per file is not normalized).
* Collapses runs of >2 consecutive blank lines back to 2 so the output
  doesn't drift from typical formatting.
* Verifies the output parses with ``ast.parse`` before writing.  An
  output that doesn't parse is a bug in this script, not a file the
  caller should accept; the script raises rather than emitting it.

Usage::

    python scripts/strip_comments.py SRC DST
    python scripts/run.py strip-comments SRC DST

``SRC`` may be a single ``.py`` file or a directory tree.  When a tree,
walks ``*.py`` files (excluding ``__pycache__/``, ``dist/``, ``build/``,
``.venv/``), preserves the relative path under ``DST``, and applies the
strip to each.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path

_LINT_EXCEPTION_PATTERN = re.compile(
    r"#\s*(noqa|type:\s*ignore|pylint:\s*disable|pragma:\s*no\s*cover|mypy:|ruff:)",
    re.IGNORECASE,
)


def _strip_docstrings(source: str) -> str:
    """Removes docstrings; inserts ``pass`` where the body would become empty.

    Drops and pass-inserts are computed from one AST pass because after
    the docstring is gone the body may no longer parse, blocking a
    second walk.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    drop_ranges: list[tuple[int, int]] = []
    pass_inserts: list[tuple[int, str]] = []

    def has_docstring(node: ast.AST) -> bool:
        body = getattr(node, "body", None)
        return bool(
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        )

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if has_docstring(node):
                docstring = node.body[0]
                start = docstring.lineno
                end = docstring.end_lineno or start
                drop_ranges.append((start, end))
                if (
                    isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and len(node.body) == 1
                ):
                    header_line = lines[node.lineno - 1]
                    base_indent = header_line[: len(header_line) - len(header_line.lstrip())]
                    body_indent = base_indent + "    "
                    pass_inserts.append((end, body_indent + "pass\n"))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)

    edits = [("drop", start, end, None) for (start, end) in drop_ranges]
    edits += [("insert", start, start, text) for (start, text) in pass_inserts]
    edits.sort(key=lambda item: item[1], reverse=True)

    for kind, start, end, text in edits:
        if kind == "drop":
            del lines[start - 1 : end]
        else:
            lines.insert(start, text)

    return "".join(lines)


def _strip_comments(source: str) -> str:
    """Removes ``#`` comments unless they carry a lint-exception annotation."""
    output: list[str] = []
    for raw_line in source.splitlines(keepends=True):
        stripped = raw_line.lstrip()
        if stripped.startswith("#"):
            if _LINT_EXCEPTION_PATTERN.search(stripped):
                output.append(raw_line)
            continue
        in_string: str | None = None
        comment_index: int | None = None
        column = 0
        while column < len(raw_line):
            ch = raw_line[column]
            if in_string is None:
                if raw_line[column : column + 3] in ('"""', "'''"):
                    in_string = raw_line[column : column + 3]
                    column += 3
                    continue
                if ch == '"' or ch == "'":
                    in_string = ch
                elif ch == "#":
                    comment_index = column
                    break
            else:
                if len(in_string) == 3:
                    if raw_line[column : column + 3] == in_string:
                        in_string = None
                        column += 3
                        continue
                elif ch == in_string and (column == 0 or raw_line[column - 1] != "\\"):
                    in_string = None
            column += 1
        if comment_index is None:
            output.append(raw_line)
            continue
        trailing = raw_line[comment_index:]
        if _LINT_EXCEPTION_PATTERN.search(trailing):
            output.append(raw_line)
            continue
        prefix = raw_line[:comment_index].rstrip()
        if prefix:
            output.append(prefix + "\n")
    return "".join(output)


def _collapse_blank_runs(source: str) -> str:
    """Caps runs of blank lines at two to keep the output close to typical formatting."""
    result: list[str] = []
    blank_run = 0
    for line in source.splitlines(keepends=True):
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                result.append(line)
        else:
            blank_run = 0
            result.append(line)
    return "".join(result)


def strip_file(src_text: str) -> str:
    """Strips one Python source string and returns the cleaned text.

    Raises:
        SyntaxError: When the input doesn't parse, or when the stripped
            output unexpectedly fails to parse (a script bug).
    """
    intermediate = _strip_docstrings(src_text)
    intermediate = _strip_comments(intermediate)
    cleaned = _collapse_blank_runs(intermediate)
    ast.parse(cleaned)
    return cleaned


def _iter_target_files(source: Path) -> Iterable[Path]:
    if source.is_file():
        yield source
        return
    skip_dirs = {"__pycache__", "dist", "build", ".venv", ".eggs"}
    for path in sorted(source.rglob("*.py")):
        if any(part in skip_dirs for part in path.parts):
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Strip docstrings and non-lint comments from Python source.",
    )
    parser.add_argument("src", help="source file or directory tree")
    parser.add_argument("dst", help="output file (when src is a file) or directory")
    parser.add_argument(
        "--quiet", action="store_true", help="suppress per-file progress output",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.src)
    dst_path = Path(args.dst)

    if not source_path.exists():
        print(f"error: source not found: {source_path}", file=sys.stderr)
        return 1

    if source_path.is_file():
        if dst_path.is_dir():
            dst_file = dst_path / source_path.name
        else:
            dst_file = dst_path
        text = source_path.read_text(encoding="utf-8")
        try:
            cleaned = strip_file(text)
        except SyntaxError as exception:
            print(f"error: {source_path}: {exception}", file=sys.stderr)
            return 1
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_text(cleaned, encoding="utf-8")
        if not args.quiet:
            print(f"  stripped {source_path} -> {dst_file}")
        return 0

    failures = 0
    for path in _iter_target_files(source_path):
        rel = path.relative_to(source_path)
        out_path = dst_path / rel
        text = path.read_text(encoding="utf-8")
        try:
            cleaned = strip_file(text)
        except SyntaxError as exception:
            print(f"error: {path}: {exception}", file=sys.stderr)
            failures += 1
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(cleaned, encoding="utf-8")
        if not args.quiet:
            print(f"  stripped {rel}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
