#!/usr/bin/env python3
"""Deterministic flag-only watcher: AI discourse-marker TICS + voice-descriptor LEAKS (no LLM).

Two cheap string checks over the finished file's docstrings/comments, flag-only -- never rewrites. The flags
surface in report.html next to the legibility flags; the human cuts them in the refine loop (re-roll /
tighten / write-it-myself). Both phenomena are EXACT-STRING detectable, so this needs no clean-room call.

- TICS: formulaic emphasis scaffolding LLMs over-produce ("That's the whole X", "Here's the thing", "the one
  thing ...", "This is the X that ...", "it's not X, it's Y"). Content-free; flag for the human to cut.
- LEAKS: a distinctive phrase from the ACTIVE VOICE's descriptor (e.g. cutler's "3 a.m.", "battle-tested")
  that appears in the comments but NOT in the code -- the writer pasted voice-flavor where it does not belong.
  A role-assignment framing ("You are a ...") leaks more; skipped for voiceless 'plain' (no descriptor).

Writes <rundir>/tics.json {flags:[{symbol, kind, text, why}]}.
Usage: flag_tics.py <rundir> <voice>
"""
import ast
import io
import json
import os
import re
import sys
import tokenize

SKILL = os.path.dirname(os.path.abspath(__file__))

TIC_PATTERNS = [
    (r"\bthat'?s it\.\s+that'?s\b", "doubled emphatic ('That's it. That's …')"),
    (r"\bthat'?s the whole\b", "filler emphasis ('that's the whole …')"),
    (r"\bthat is the whole\b", "filler emphasis ('that is the whole …')"),
    (r"\bthe whole (?:job|movie|drama|point|thing|deal|circus|gig|ballgame|story|show)\b", "filler ('the whole …')"),
    (r"\bhere'?s the (?:thing|deal|kicker|catch|rub|gist|trick|point)\b", "throat-clearing ('here's the …')"),
    (r"\bthe one thing\b", "filler ('the one thing …')"),
    (r"\bthis is the \w+ that\b", "indirection ('this is the X that …')"),
    (r"\bthat'?s the (?:thing|kicker|catch|rub|magic|beauty|gist)\b", "filler ('that's the …')"),
    (r"\bit'?s not (?:just )?\w[\w '-]{0,28}?,? it'?s\b", "false-insight frame ('it's not X, it's Y')"),
    (r"\bnot just \w[\w '-]{0,28}? but\b", "false-insight frame ('not just X but Y')"),
    # setup scaffolding -- the "let me prepare you for a fact" frame. Surfaced 2026-06-10: a heartbeat run
    # shipped "One thing to know going in:" unflagged, and the same family ran 4-deep in the older arm
    # ("The honesty up front:", "One more thing the name hides:", "Two details worth knowing.").
    (r"\bone thing to know\b", "setup scaffolding ('one thing to know …')"),
    (r"\bone more thing\b", "setup scaffolding ('one more thing …')"),
    (r"\bworth (?:knowing|noting)\b", "setup scaffolding ('… worth knowing/noting')"),
    (r"\b(?:to know|knowing|honesty|truth) (?:going in|up front)\b", "setup scaffolding ('… going in / up front')"),
]

STOP = set(
    "a an and the of to in is are was for on at by or but as with that this it its their his her you your "
    "they them then than when where how what which who whom whose will would can could should may might must "
    "still about like over into onto less more most some any all each every both either neither no not so if "
    "up out off down here there now just very really only also even much many few whether while because".split())


def signatures(descriptor):
    """Distinctive phrases from the voice descriptor that would be OUT OF PLACE in a code comment."""
    d = descriptor.lower()
    sigs = set()
    sigs |= {m for m in re.findall(r"\b\w+(?:-\w+)+\b", d) if len(m) >= 6}          # hyphenated compounds
    sigs |= {re.sub(r"\s+", " ", m).strip() for m in re.findall(r"\b\d{1,2}\s*[ap]\.?m\.?", d)}  # clock (3 a.m.)
    words = re.findall(r"[a-z][a-z'-]+", d)                                          # content 2-3-word phrases
    for n in (3, 2):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if all(w not in STOP and len(w) > 3 for w in gram):
                sigs.add(" ".join(gram))
    return {s for s in sigs if len(s) >= 5}


def comment_units(src):
    """(line, text) for every docstring SENTENCE and every inline # comment in the file."""
    tree = ast.parse(src)
    units = []
    nodes = [tree] + [n for n in ast.walk(tree)
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in nodes:
        ds = ast.get_docstring(node)
        if ds:
            ln = node.body[0].lineno if getattr(node, "body", None) else 1
            for sent in re.split(r"(?<=[.!?])\s+", ds.strip()):
                if sent.strip():
                    units.append((ln, sent.strip()))
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            t = tok.string.lstrip("#").strip()
            if t:
                units.append((tok.start[0], t))
    return tree, units


def symbol_spans(tree):
    spans = []

    def walk(node, prefix):
        for c in ast.iter_child_nodes(node):
            if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + c.name
                start = min([c.lineno] + [d.lineno for d in getattr(c, "decorator_list", [])])
                spans.append((q, start, c.end_lineno))
                walk(c, q + ".")

    walk(tree, "")
    return spans


def scan(src, sigs, code):
    """Flag every tic/leak in src's docstrings + comments — the reusable core of this watcher.

    Also used by autoroute_tics.py to test whether an alternative pass's take on a symbol is clean.
    """
    tree, units = comment_units(src)
    spans = symbol_spans(tree)

    def sym_at(line):
        best = ("<module>", -1)
        for q, s, e in spans:
            if s <= line <= e and s > best[1]:
                best = (q, s)
        return best[0]

    flags, seen = [], set()
    for line, text in units:
        low = text.lower()
        sym = sym_at(line)
        for pat, why in TIC_PATTERNS:                       # discourse-marker tics
            if re.search(pat, low):
                key = ("tic", sym, text)
                if key not in seen:
                    seen.add(key)
                    flags.append({"symbol": sym, "kind": "tic", "text": text, "why": why})
                break
        matched = [sig for sig in sigs if sig in low and sig not in code]   # descriptor leaks
        if matched:
            sig = max(matched, key=len)                     # report the most specific phrase
            key = ("leak", sym, sig)
            if key not in seen:
                seen.add(key)
                flags.append({"symbol": sym, "kind": "leak", "text": text,
                              "why": f"voice-descriptor phrase \"{sig}\" leaked into a comment (not in the code)"})
    return flags


def main():
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    out = os.path.join(rundir, "tics.json")
    if not os.path.exists(final):
        json.dump({"flags": []}, open(out, "w"))
        return
    src = open(final).read()
    spath = os.path.join(rundir, "stripped.py")
    code = open(spath).read().lower() if os.path.exists(spath) else ""
    descriptor = json.load(open(os.path.join(SKILL, "voices.json")))["voices"].get(voice, "")

    sigs = signatures(descriptor) if descriptor else set()
    flags = scan(src, sigs, code)
    json.dump({"flags": flags}, open(out, "w"), indent=2)
    nt = sum(1 for f in flags if f["kind"] == "tic")
    nl = sum(1 for f in flags if f["kind"] == "leak")
    print(f"=== TIC/LEAK FLAGS: {nt} tic(s), {nl} leak(s) -> {out} ===")


if __name__ == "__main__":
    main()
