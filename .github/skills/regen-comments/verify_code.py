#!/usr/bin/env python3
"""Confirm a finished file changed ONLY docstrings and comments, never executable code.

The regen pipeline must leave the code byte-identical -- it adds and rewrites docstrings and `#` comments
and nothing else. This checks that mechanically so the orchestrator does not hand-roll it. (An earlier
hand-rolled check fed `strip.py` and read its stdout as if it were the stripped code; `strip.py` writes to
a file and prints only a `stripped X -> Y` line, so the empty capture looked like a mismatch.) Here the
comparison is structural: parse both files, drop every docstring node from both trees, and compare the AST
dumps with line numbers excluded, so an added docstring that shifts lines does not register as a change.
Comments never reach the AST, so they are ignored for free. The finished file is also compiled, so a
syntax error is caught as the loudest possible failure rather than slipping through as "identical".

Exit 0 + "CODE IDENTICAL" when the executable code matches. Exit 1 + the first differing construct when it
does not, or + the compile error when the finished file will not parse.

Usage: verify_code.py <original.py> <final.py>
"""
import ast
import difflib
import sys


def _strip_docstrings(tree):
    """Remove the leading string-literal statement from the module and every def/class in the tree.

    Mutates in place and returns the tree. Walking after the mutation is safe: ``ast.walk`` queues each
    node's children before yielding the node, so a detached docstring may still be yielded once, but it is
    an inert ``Expr`` we never act on.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:]
    return tree


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: verify_code.py <original.py> <final.py>")
    orig_src = open(sys.argv[1]).read()
    final_src = open(sys.argv[2]).read()

    # Compile the finished file first: a syntax error here is the loudest failure and must not read as a pass.
    try:
        compile(final_src, sys.argv[2], "exec")
    except SyntaxError as e:
        sys.exit(f"FINISHED FILE DOES NOT COMPILE: {e}")

    orig = ast.dump(_strip_docstrings(ast.parse(orig_src)), indent=2)
    final = ast.dump(_strip_docstrings(ast.parse(final_src)), indent=2)
    if orig == final:
        print("CODE IDENTICAL: executable code unchanged (only docstrings/comments differ); finished file compiles.")
        return

    # Show the first divergence so a human can see WHAT moved, not just that something did.
    diff = list(difflib.unified_diff(orig.splitlines(), final.splitlines(),
                                     fromfile="original (code only)", tofile="final (code only)", lineterm=""))
    print("CODE CHANGED: executable code differs after stripping docstrings -- this should never happen.")
    print("\n".join(diff[:40]))
    sys.exit(1)


if __name__ == "__main__":
    main()
