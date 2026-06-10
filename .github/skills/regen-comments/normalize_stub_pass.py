#!/usr/bin/env python3
"""Remove a `pass` made redundant by a regenerated docstring (mechanical, no LLM).

strip.py replaces a docstring-only class/function body with `pass` to keep the stripped file
syntactically valid. A writer adding its docstring back sometimes keeps that `pass` and sometimes
drops it — both are faithful to the stripped input, but only the dropped form is byte-identical to
an original whose body was the docstring alone, so the kept form fails the invariant-4 verify and
would land a stray `pass` in the human's diff. This normalizer deletes every `pass` whose enclosing
body is exactly [docstring, pass], bringing all writer passes to the docstring-only form.

A body of [docstring, pass] never carries meaning the docstring-only form lacks; an original that
genuinely spelled both still fails verify loudly afterward (rare, and no worse than before).

Usage: normalize_stub_pass.py <file.py> [...]    (in-place; prints one line per changed file)
Exposes normalize(path) -> bool for regen_phase2.py.
"""
import ast
import sys


def normalize(path):
    source = open(path).read()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    doomed_lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (len(body) == 2 and isinstance(body[1], ast.Pass)
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            doomed_lines.add(body[1].lineno)
    if not doomed_lines:
        return False
    lines = source.splitlines(keepends=True)
    kept = [line for number, line in enumerate(lines, 1)
            if not (number in doomed_lines and line.strip() == "pass")]
    new_source = "".join(kept)
    ast.parse(new_source)  # refuse to write anything that no longer parses
    open(path, "w").write(new_source)
    return True


def main():
    for path in sys.argv[1:]:
        if normalize(path):
            print(f"normalized: dropped docstring-redundant pass in {path}")


if __name__ == "__main__":
    main()
