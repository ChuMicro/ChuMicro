#!/usr/bin/env python3
"""Deterministic detector for the mechanical writing-tic bans (no LLM).

Finds the violations the writer discipline calls absolute — em-dashes, semicolons, and the banned words
`canonical` / `shape` — in a file's DOCSTRINGS and COMMENTS only (executable code is never inspected). The
polish step uses this to know exactly what to fix and to confirm a clean result; nothing here rewrites prose
(that needs judgment). (Sentence-opener bans were intentionally dropped — they flattened the voice.)

Usage: tics.py <file.py>      # prints violations, exit 1 if any
       from tics import detect # -> [{kind, where, text}]
"""
import ast
import io
import re
import sys
import tokenize

BANNED_WORDS = ("canonical", "shape")


def _strip_code_spans(text):
    return re.sub(r"`[^`]*`", "", text)  # drop ``code`` so a semicolon/word inside an example is ignored


def _scan(text, where, out):
    bare = _strip_code_spans(text)
    if "—" in bare:
        out.append({"kind": "em-dash", "where": where, "text": text.strip()[:90]})
    # the double-hyphen em-dash stand-in counts as an em-dash: writers mimic the prompts' own " -- "
    # punctuation, and the character-only check let it ship all day (caught 2026-06-10)
    if " -- " in bare or bare.rstrip().endswith(" --"):
        out.append({"kind": "em-dash", "where": where, "text": text.strip()[:90]})
    if ";" in bare:
        out.append({"kind": "semicolon", "where": where, "text": text.strip()[:90]})
    for w in BANNED_WORDS:
        if re.search(rf"\b{w}\b", bare, re.IGNORECASE):
            out.append({"kind": f"banned-word:{w}", "where": where, "text": text.strip()[:90]})


def detect(src):
    out = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                name = getattr(node, "name", "<module>")
                _scan(doc, f"docstring:{name}", out)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                body = tok.string.lstrip("#").strip()
                if body:
                    _scan(body, f"comment:L{tok.start[0]}", out)
    except tokenize.TokenError:
        pass
    return out


def main():
    src = open(sys.argv[1]).read()
    v = detect(src)
    for it in v:
        print(f"  [{it['kind']}] {it['where']}: {it['text']}")
    print(f"{len(v)} tic violation(s) in {sys.argv[1]}")
    sys.exit(1 if v else 0)


if __name__ == "__main__":
    main()
