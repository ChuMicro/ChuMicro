#!/usr/bin/env python3
"""Stage 6 — PRESERVE-AND-REATTACH (mechanical, no LLM, fixture-agnostic).

Rides the comment lens's PRESERVE lane back onto a finished (clean-room-written) file, verbatim. The
preserve lane is DATA from the comment lens (never hardcoded): a JSON list of {line, placement}, where
placement is "header-top" (copyright/author/license -> file top) or "inline" (a live directive/TODO ->
after the module docstring). A writer never reworded these; this is the deterministic merge that puts
provenance/tracker metadata back. The human picker may already have dropped borderline preserve items, so
this reattaches exactly what the final preserve.json carries.

Usage: reattach.py <written.py> <preserve.json> <out.py>
preserve.json: [{"line": "# Copyright ...", "placement": "header-top"}, {"line": "# TODO(...)", "placement": "inline"}]
"""
import ast
import json
import sys


def _as_comment(line):
    """Guarantee a preserved line reattaches as a valid comment.

    Preserve items are always comments (copyright, license, TODO, attributed notes). When the comment lens
    slips and stores a line WITHOUT its leading ``#`` (it stripped a ``# -- section --`` divider down to its
    inner text), inserting it verbatim drops bare text into the file and breaks compilation. Prepend ``# ``
    when the marker is missing; drop a blank line entirely.
    """
    s = line.strip()
    if not s:
        return None
    return line if s.startswith("#") else "# " + line


def reattach(written_src, preserve):
    header = [c for c in (_as_comment(p["line"]) for p in preserve if p.get("placement") == "header-top") if c]
    inline = [c for c in (_as_comment(p["line"]) for p in preserve if p.get("placement") == "inline") if c]
    lines = written_src.splitlines()
    doc_end = 0
    try:
        tree = ast.parse(written_src)
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)):
            doc_end = tree.body[0].value.end_lineno
    except SyntaxError:
        pass
    if doc_end:                      # header at top, inline directives just after the module docstring
        out = header + lines[:doc_end] + inline + lines[doc_end:]
    else:                            # no module docstring -> header + inline ahead of the first code line
        out = header + inline + lines
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    written = open(sys.argv[1]).read()
    preserve = json.load(open(sys.argv[2]))
    open(sys.argv[3], "w").write(reattach(written, preserve))
    print(f"reattached {len(preserve)} preserve line(s) -> {sys.argv[3]}")
