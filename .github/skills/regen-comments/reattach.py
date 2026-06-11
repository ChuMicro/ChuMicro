#!/usr/bin/env python3
"""Stage 6 — PRESERVE-AND-REATTACH (mechanical, no LLM, fixture-agnostic).

Rides the comment lens's PRESERVE lane back onto a finished (clean-room-written) file. The preserve lane is
DATA from the comment lens (never hardcoded): a JSON list of {line, placement, anchor_code, attach}, where
placement is "header-top" (copyright/author/license -> file top) or "inline" (a directive/TODO/note tied to a
code location). A writer never reworded these; this is the deterministic merge that puts provenance/tracker
metadata back.

PLACEMENT of inline items: the executable code is byte-identical between the original and the finished file,
so an inline item carries ``anchor_code`` (the exact source text of the code line it belongs to) + ``attach``
("trailing" to append the directive to that line, e.g. ``# noqa``; "above" to put a standalone comment on its
own line above it). We find that code line in the finished file and place the item there. A ``# noqa`` MUST
sit on its own line, so dropping every inline item after the module docstring (the old behavior) was wrong.
When an item has no usable anchor, or the anchor is missing / not unique, it falls back to just after the
module docstring -- never worse than before.

Usage: reattach.py <written.py> <preserve.json> <out.py>
"""
import ast
import json
import sys
from collections import defaultdict


def _as_comment(line):
    """Guarantee a preserved line reattaches as a valid comment (prepend '# ' if its marker was dropped)."""
    s = line.strip()
    if not s:
        return None
    return line if s.startswith("#") else "# " + line


def _indent(s):
    return s[: len(s) - len(s.lstrip())]


def reattach(written_src, preserve):
    lines = written_src.splitlines()
    header = [c for c in (_as_comment(p["line"]) for p in preserve if p.get("placement") == "header-top") if c]
    inline = [p for p in preserve if p.get("placement") == "inline"]

    # map each unique code line (stripped, non-comment) to its index, for anchoring inline items
    code_index = defaultdict(list)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s and not s.startswith("#"):
            code_index[s].append(i)

    fallback, above = [], []
    for p in inline:
        comment = _as_comment(p["line"])
        if comment is None:
            continue
        anchor = (p.get("anchor_code") or "").strip()
        idxs = code_index.get(anchor, [])
        if anchor and len(idxs) == 1:                       # unique code line to attach to
            i = idxs[0]
            if p.get("attach") == "trailing":               # ``# noqa`` rides the end of its code line:
                # append only the directive suffix to the FILE's own code line -- restoring the lens's
                # stored line verbatim once broke compilation when the lens recorded it with the wrong
                # indentation (kvstore core.py 2026-06-10: an ``if`` re-indented 4->8 spaces)
                suffix = p["line"][p["line"].index("#"):].rstrip() if "#" in p["line"] else ""
                if suffix and suffix not in lines[i]:
                    lines[i] = lines[i].rstrip() + "  " + suffix
            else:                                           # standalone comment on its own line above
                above.append((i, _indent(lines[i]) + comment.strip()))
        else:                                               # no usable anchor -> legacy doc-relative spot
            fallback.append(comment)

    for i, text in sorted(above, key=lambda t: -t[0]):      # bottom-up so earlier inserts don't shift indices
        lines.insert(i, text)

    # module docstring end (recomputed after edits); header on top, un-anchored inline items just after it
    doc_end = 0
    try:
        tree = ast.parse("\n".join(lines))
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str)):
            doc_end = tree.body[0].value.end_lineno
    except SyntaxError:
        pass
    if doc_end:
        out = header + lines[:doc_end] + fallback + lines[doc_end:]
    else:
        out = header + fallback + lines
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    written = open(sys.argv[1]).read()
    preserve = json.load(open(sys.argv[2]))
    open(sys.argv[3], "w").write(reattach(written, preserve))
    print(f"reattached {len(preserve)} preserve line(s) -> {sys.argv[3]}")
