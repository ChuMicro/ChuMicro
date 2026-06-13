"""Strip docstrings and comments from Python source bound for a device.

``strip_source`` removes module / class / function docstrings and every
``#`` comment while leaving the executable code untouched, so a deployed
file's byte size tracks its code rather than its prose.  Comments and
docstrings are the bulk of a staged ``.py`` file, and they drift in size
as they are rewritten; stripping them keeps the deployed bytes stable and
shrinks the flash footprint.

``strip_source`` blanks removed docstrings and comments rather than deleting
their lines, so every kept statement keeps its original line number.  That
matters because the on-device test runner splits a staged file at top-level
statement line numbers it computed from the unstripped source, and because a
device traceback then points at the right line.  It also compares the parse
tree of the stripped output against the parse tree of the input (both with
docstrings removed) and returns the input verbatim if they differ.  That
guard makes the cheap line-and-string comment scan safe: a file the scanner
would corrupt (for example a ``#`` inside a multi-line string) deploys
unstripped instead of broken.

``minify_python_tree`` applies ``strip_source`` to every ``.py`` file under
a staging directory in place, just before the directory is copied to the
board.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import cast


def strip_source(source: str) -> str:
    """Return *source* with docstrings and comments removed, or *source* unchanged.

    Drops module / class / function docstrings and every ``#`` comment.
    Returns *source* untouched when it does not parse, when the stripped
    text would not parse, or when stripping changed anything beyond the
    docstrings (the equivalence guard) so a miss never ships broken code.
    """
    try:
        original_tree = ast.parse(source)
    except SyntaxError:
        return source

    candidate = _strip_line_comments(_strip_leading_docstrings(source))

    try:
        candidate_tree = ast.parse(candidate)
    except SyntaxError:
        return source

    if _code_signature(original_tree) != _code_signature(candidate_tree):
        return source
    return candidate


def minify_python_tree(root: Path) -> None:
    """Rewrite every ``.py`` file under *root* in place via :func:`strip_source`.

    Walks the staging tree, strips each Python file's docstrings and
    comments, and writes the result back only when it changed.  Files that
    are not valid Python, or whose strip would alter code, are left as they
    are because :func:`strip_source` returns them verbatim.
    """
    for path in sorted(root.rglob("*.py")):
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        stripped = strip_source(original)
        if stripped != original:
            path.write_text(stripped, encoding="utf-8")


def _strip_leading_docstrings(source: str) -> str:
    """Return *source* with each leading docstring blanked in place.

    A leading docstring is the first statement of a ``Module``,
    ``ClassDef``, ``FunctionDef``, or ``AsyncFunctionDef`` body when it is a
    bare string constant.  Replaces the docstring's lines with blank lines,
    putting a single ``pass`` on the first of them when the docstring was the
    only statement in a class or function body.  Keeping one output line per
    input line holds every later statement on its original line number.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    replacements: list[tuple[int, int, list[str]]] = []

    def has_docstring(node: ast.AST) -> bool:
        body = getattr(node, "body", None)
        return bool(
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        )

    def visit(node: ast.AST) -> None:
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and has_docstring(node)
        ):
            docstring = node.body[0]
            start = docstring.lineno
            end = docstring.end_lineno or start
            span = end - start + 1
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and len(node.body) == 1
            ):
                header_line = lines[node.lineno - 1]
                base_indent = header_line[: len(header_line) - len(header_line.lstrip())]
                replacement = [base_indent + "    pass\n"] + ["\n"] * (span - 1)
            else:
                replacement = ["\n"] * span
            replacements.append((start, end, replacement))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)

    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        lines[start - 1 : end] = replacement

    return "".join(lines)


def _strip_line_comments(source: str) -> str:
    """Return *source* with every ``#`` comment blanked in place.

    Tracks single- and triple-quoted string state within each line so a
    ``#`` inside a string literal stays, while a real comment is dropped.  A
    full-line comment becomes a blank line rather than vanishing, so each
    input line maps to one output line and statement line numbers hold.
    String state resets per line, so the multi-line-string case is caught
    instead by the equivalence guard in :func:`strip_source`.
    """
    output: list[str] = []
    for raw_line in source.splitlines(keepends=True):
        if raw_line.lstrip().startswith("#"):
            output.append("\n")
            continue
        in_string: str | None = None
        comment_index: int | None = None
        column = 0
        while column < len(raw_line):
            character = raw_line[column]
            if in_string is None:
                if raw_line[column : column + 3] in ('"""', "'''"):
                    in_string = raw_line[column : column + 3]
                    column += 3
                    continue
                if character == '"' or character == "'":
                    in_string = character
                elif character == "#":
                    comment_index = column
                    break
            else:
                if len(in_string) == 3:
                    if raw_line[column : column + 3] == in_string:
                        in_string = None
                        column += 3
                        continue
                elif character == in_string and (column == 0 or raw_line[column - 1] != "\\"):
                    in_string = None
            column += 1
        if comment_index is None:
            output.append(raw_line)
            continue
        # A line whose only content before the ``#`` is whitespace already
        # matched the full-line-comment check above, so the kept prefix here
        # always carries code.
        output.append(raw_line[:comment_index].rstrip() + "\n")
    return "".join(output)


def _code_signature(tree: ast.Module) -> str:
    """Return a position-independent dump of *tree* with all docstrings removed.

    Two trees share a signature when their code is identical apart from
    docstrings, so comparing signatures tells :func:`strip_source` whether a
    strip touched anything but the docstrings and comments it was meant to.
    Mutates *tree* in place; the caller passes a tree it does not reuse.
    """
    stripped = _DocstringStripper().visit(tree)
    ast.fix_missing_locations(stripped)
    return ast.dump(stripped, include_attributes=False)


class _DocstringStripper(ast.NodeTransformer):
    """Remove the leading docstring from every scope it visits.

    The visit methods cast ``generic_visit`` back to the specific node
    type.  ``ast.NodeTransformer.generic_visit`` is typed as returning
    ``AST``, but a ``visit_<Specific>`` method that mutates in place returns
    the same node type it was handed.
    """

    def visit_Module(self, node: ast.Module) -> ast.Module:
        node.body = _strip_docstring_from_body(node.body)
        return cast(ast.Module, self.generic_visit(node))

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        node.body = _strip_docstring_from_body(node.body, require_nonempty=True)
        return cast(ast.ClassDef, self.generic_visit(node))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.body = _strip_docstring_from_body(node.body, require_nonempty=True)
        return cast(ast.FunctionDef, self.generic_visit(node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        node.body = _strip_docstring_from_body(node.body, require_nonempty=True)
        return cast(ast.AsyncFunctionDef, self.generic_visit(node))


def _strip_docstring_from_body(
    body: list[ast.stmt],
    *,
    require_nonempty: bool = False,
) -> list[ast.stmt]:
    """Return *body* with a leading docstring statement removed.

    Replaces an emptied body with a single ``pass`` when *require_nonempty*
    is set, so a class or function that held nothing but a docstring stays
    syntactically valid.
    """
    if not body:
        return [ast.Pass()] if require_nonempty else body

    first_statement = body[0]
    if not isinstance(first_statement, ast.Expr):
        return body
    if not isinstance(first_statement.value, ast.Constant):
        return body
    if not isinstance(first_statement.value.value, str):
        return body
    stripped_body = body[1:]
    if stripped_body:
        return stripped_body
    if require_nonempty:
        return [ast.Pass()]
    return stripped_body
