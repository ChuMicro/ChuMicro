#!/usr/bin/env python3
"""Enforce the mechanical writing-tic bans on a finished file (SKILL.md Step 5, wired).

Detects banned sentence-openers / em-dashes / semicolons / banned words (tics.py), then runs a clean-room
`claude -p` that rewrites ONLY the offending docstring/comment sentences — minimal, meaning-preserving, voice
intact, executable code byte-identical. Loops until the deterministic detector is clean or MAX attempts. The
executable-code fingerprint (docstrings stripped) is checked after each pass; a pass that changed code is
reverted. Generators drift on "no exceptions" style rules, so this is the backstop that actually guarantees
the bans hold in the delivered file.

Usage: polish.py <rundir> <file.py>
"""
import ast
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from tics import detect  # noqa: E402

MAX = 3


def _code_fingerprint(src):
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value, str):
                n.body = b[1:] or [ast.Pass()]
    return ast.dump(tree)


def _polish_once(rundir, fname, offenders):
    lines = "\n".join(f"  - [{o['kind']}] {o['where']}: {o['text']}" for o in offenders)
    prompt = (
        "Read the Python file ./" + fname + ". Some docstrings/comments violate absolute mechanical writing "
        "rules. Fix EVERY violation listed below by minimally rewriting ONLY those docstring/comment "
        "sentences. Keep the meaning and the voice; change as few words as possible.\n"
        "Rules (absolute):\n"
        "- No sentence may START with The, That, That's, This, These, or Those. Recast with a concrete noun "
        "or a precise verb (e.g. 'The header carries X' -> 'A 10-byte header carries X', or name the actor).\n"
        "- No em-dashes (use a period or comma). No semicolons (split into two sentences). Never use the "
        "words 'canonical' or 'shape' in any form.\n"
        "- Do NOT change any executable code, and do NOT touch any line that is not a docstring or comment. "
        "Keep directive comments (# noqa, # type: ignore, etc.) verbatim.\n\n"
        "VIOLATIONS:\n" + lines + "\n\nEdit the file in place and reply DONE."
    )
    subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read", "Edit", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )


def main():
    rundir = os.path.abspath(sys.argv[1])
    path = sys.argv[2]
    path = path if os.path.isabs(path) else os.path.join(rundir, path)
    fname = os.path.relpath(path, rundir)
    fp0 = _code_fingerprint(open(path).read())

    for attempt in range(1, MAX + 1):
        v = detect(open(path).read())
        if not v:
            print(f"=== POLISH CLEAN (after {attempt - 1} pass(es)) ===")
            return
        print(f"polish attempt {attempt}: {len(v)} violation(s)")
        backup = f"{path}.pre{attempt}"
        shutil.copy(path, backup)
        _polish_once(rundir, fname, v)
        if _code_fingerprint(open(path).read()) != fp0:
            print("  polish changed executable code -> reverting that pass")
            shutil.copy(backup, path)
            break

    v = detect(open(path).read())
    print(f"=== POLISH DONE: {len(v)} violation(s) remain ===")
    for it in v:
        print(f"  [{it['kind']}] {it['where']}: {it['text']}")


if __name__ == "__main__":
    main()
