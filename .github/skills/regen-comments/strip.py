#!/usr/bin/env python3
"""Mechanical comment/docstring stripper for the regen-comments skill (no LLM).

Produces the clean-room input the writers annotate: executable code byte-identical to the original, with
all comments and docstrings removed. Line surgery (not ast.unparse, which would reformat) preserves the
code exactly. A docstring that is the SOLE statement of a function/class body is replaced by `pass` so the
result still parses; a module-level-only docstring just leaves an empty module. Inline comments are cut at
the `#` (found via tokenize, so `#` inside strings is safe); comment-only lines are dropped.

Usage: strip.py <in.py> <out.py>   (also: from strip import strip_code)
"""
import ast
import io
import sys
import tokenize


def _is_docstring(stmt):
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def extract_header(src):
    """Leading copyright/license/author/shebang comment block — preserved regardless of comment-triage mode.

    Returns the run of `#` lines at the very top of the file, before any code, import, or the module
    docstring, as preserve-lane header items ({line, placement: "header-top"}). strip() drops these like
    any other comment; this lets the orchestrator ride them back verbatim even when comment-triage is off,
    so a license header is never silently eaten. Blank lines inside the run are skipped (cosmetic), and the
    scan stops at the first non-comment, non-blank line.
    """
    items = []
    for line in src.splitlines():
        s = line.strip()
        if s == "":
            continue
        if s.startswith("#"):
            items.append({"line": line.rstrip(), "placement": "header-top"})
        else:
            break
    return items


def strip_code(src):
    drop_lines = set()            # 1-based line numbers to remove entirely
    replace_pass = {}             # docstring-only body: lineno -> indent col for `pass`
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if body and _is_docstring(body[0]):
                    d = body[0]
                    for ln in range(d.lineno, d.end_lineno + 1):
                        drop_lines.add(ln)
                    if len(body) == 1 and not isinstance(node, ast.Module):
                        replace_pass[d.lineno] = d.col_offset
    except SyntaxError:
        pass

    comment_cut = {}              # lineno -> column where an inline/full comment starts
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                r, c = tok.start
                comment_cut[r] = min(comment_cut.get(r, c), c)
    except tokenize.TokenError:
        pass

    out = []
    for i, line in enumerate(src.splitlines(), start=1):
        if i in replace_pass:
            out.append(" " * replace_pass[i] + "pass")
            continue
        if i in drop_lines:
            continue
        if i in comment_cut:
            line = line[:comment_cut[i]].rstrip()
            if line == "":
                continue
        out.append(line)
    result = "\n".join(out) + "\n"
    ast.parse(result)             # guard: stripped code must still parse
    return result


if __name__ == "__main__":
    open(sys.argv[2], "w").write(strip_code(open(sys.argv[1]).read()))
    print(f"stripped {sys.argv[1]} -> {sys.argv[2]}")
