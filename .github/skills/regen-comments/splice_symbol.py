#!/usr/bin/env python3
"""Splice one symbol's docstring+comments from another version of the same file (the refinement primitive).

Every candidate version (the N passes) and any symbol-scoped regeneration share byte-identical EXECUTABLE
code — they differ only in docstrings and comments. So replacing a symbol's whole source span (its signature
through the end of its body) with the same symbol's span from another version swaps THAT symbol's docs and
comments and nothing else. This is the single mechanical operation behind every refinement-loop edit:
roll-the-dice candidate cycling, fresh symbol regen, and write-it-myself.

Guard: after the splice, the executable code (docstrings stripped) must be AST-equal to the original — if it
is not, the source version drifted the code and the splice is rejected.

Usage: splice_symbol.py <current.py> <source.py> <qualname> <out.py>
  qualname: "<module>" (module docstring), "func", "Class", or "Class.method".
"""
import ast
import sys


def _find(tree, qual):
    parts = qual.split(".")
    node = tree
    for name in parts:
        nxt = None
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == name:
                nxt = child
                break
        if nxt is None:
            sys.exit(f"symbol {qual!r} not found")
        node = nxt
    return node


def _span(node):
    """1-based inclusive (start, end) line span of a def/class, decorators included."""
    start = node.lineno
    if getattr(node, "decorator_list", None):
        start = min(start, min(d.lineno for d in node.decorator_list))
    return start, node.end_lineno


def _module_doc_node(tree):
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str)):
        return tree.body[0]
    return None


def _code_only(src):
    """AST dump with every docstring removed — the executable-code fingerprint."""
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
                n.body = b[1:] or [ast.Pass()]
    return ast.dump(tree)


def splice(current_src, source_src, qual):
    cur_lines = current_src.splitlines()
    src_lines = source_src.splitlines()
    cur_tree = ast.parse(current_src)
    src_tree = ast.parse(source_src)

    if qual == "<module>":
        cur_doc = _module_doc_node(cur_tree)
        src_doc = _module_doc_node(src_tree)
        repl = src_lines[src_doc.lineno - 1:src_doc.end_lineno] if src_doc else []
        if cur_doc:
            new = cur_lines[:cur_doc.lineno - 1] + repl + cur_lines[cur_doc.end_lineno:]
        elif repl:
            new = repl + cur_lines
        else:
            new = cur_lines
    else:
        cs, ce = _span(_find(cur_tree, qual))
        ss, se = _span(_find(src_tree, qual))
        new = cur_lines[:cs - 1] + src_lines[ss - 1:se] + cur_lines[ce:]

    return "\n".join(new) + "\n"


def main():
    current_src = open(sys.argv[1]).read()
    source_src = open(sys.argv[2]).read()
    qual = sys.argv[3]
    out = sys.argv[4]
    result = splice(current_src, source_src, qual)
    if _code_only(result) != _code_only(current_src):
        sys.exit(f"REJECTED: splicing {qual!r} changed executable code — source version is not code-identical")
    ast.parse(result)  # guard: result still parses
    open(out, "w").write(result)
    print(f"spliced {qual!r} from {sys.argv[2]} -> {out} (code unchanged)")


if __name__ == "__main__":
    main()
