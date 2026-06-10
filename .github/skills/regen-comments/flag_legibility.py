#!/usr/bin/env python3
"""Legibility flagger: read the FINISHED file and flag any docstring/comment sentence that does not read as
clean, natural English. FLAG-ONLY, never rewrites.

The rare convoluted sentence is a stochastic roll the writer occasionally produces (a whole file has ~20-30
sentences, so even a small per-sentence chance makes one bad sentence per file common, while any single
sentence almost never is). Nothing in the pipeline watched for it, so the bad roll shipped. This is the
watcher: it surfaces a flagged sentence in the report so the human fixes it in the refine loop instead of
shipping it. Conservative by design -- it flags ONLY a sentence that genuinely reads badly, never a
merely-improvable one, so the list is signal, not noise. An empty list is the expected result for a clean
file.

Writes <rundir>/legibility.json = {flags:[{symbol, sentence, why}]}.

Usage: flag_legibility.py <rundir> <voice>
"""
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402


def main():
    require_claude()
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    final = f"FINAL_{voice}.py"
    if not os.path.exists(os.path.join(rundir, final)):
        sys.exit(f"{final} missing -- run phase 2 first.")
    # announce before the silent clean-room call so a chained refine sequence self-narrates
    print("scanning the finished file for awkward sentences (one clean-room claude -p, ~1 min)...", flush=True)
    prompt = (
        "Read the finished Python file ./" + final + ". Judge ONLY how the docstrings and `#` comments READ "
        "as English. Not their correctness, not their completeness, not the code itself.\n\n"
        "Read each sentence the way you would say it out loud to a colleague. FLAG a sentence only when it "
        "genuinely does not read like clean, natural English: an abstract clause crammed into the subject "
        "slot with a weak verb (for example `Whether X is present rather than its value is what routes the "
        "choice`), a sentence you have to re-read to parse, a pile-up of nouns, a tangled or backwards "
        "construction. A person reading your flag should immediately agree it reads badly.\n\n"
        "Be CONSERVATIVE. Flag only a sentence that clearly fails, never one that is merely improvable or a "
        "matter of taste. A clean sentence, a plain short sentence, even a slightly dry but readable one: "
        "all fine, do NOT flag them. An empty flag list is the expected, good result for a clean file. Do "
        "NOT rewrite anything, you only flag.\n\n"
        "For each flagged sentence: symbol (the qualified name like `ClassName.method` or `<module>`), "
        "sentence (the offending sentence, verbatim), why (one short phrase naming what makes it read "
        "badly). Write JSON {flags:[{symbol, sentence, why}]} to ./legibility.json and reply DONE."
    )
    subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )
    p = os.path.join(rundir, "legibility.json")
    flags = json.load(open(p)).get("flags", []) if os.path.exists(p) else []
    print("=== LEGIBILITY FLAGS ===")
    if not flags:
        print("  no sentences flagged -- reads clean.")
        return
    print(f"  {len(flags)} sentence(s) flagged for the human to review (refine loop):")
    for f in flags:
        print(f"    - [{f.get('symbol')}] {f.get('why')}")
        print(f'        "{f.get("sentence")}"')


if __name__ == "__main__":
    main()
