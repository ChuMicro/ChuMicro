#!/usr/bin/env python3
"""Refinement loop: turn a human-supplied fact into a validated telegraphic ledger stub (clean-room).

For the add-fact / correction path. Runs one clean-room `claude -p` that reads the stripped code and the
human's plain-English fact, then: validates it against the code (confirmed / contradicted / unverifiable),
writes a telegraphic stub (never a copyable sentence), and flags whether the orchestrator should ask the
human for a source. Writes `<rundir>/stub_result.json`. The orchestrator decides what to do with the
verdict — append to the ledger and regen, push back on a contradiction (without blocking), or for an
unverifiable note ask for a source, trust the human, or route it to a NOTE(<initials>): preserve comment.

Usage: stubify_fact.py <rundir> "<the human's fact, plain English>"
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
    fact = sys.argv[2]
    prompt = (
        "You convert a human-supplied fact into a telegraphic LEDGER STUB and VALIDATE it against the code. "
        "Reason only from the code.\n\nCODE: ./stripped.py\n\nThe human asserts:\n\"\"\"" + fact + "\"\"\"\n\n"
        "(1) status: 'confirmed' if the code supports the fact; 'contradicted' if the code shows the opposite "
        "(quote the conflicting site in note); 'unverifiable' if it cannot be checked from code alone (a "
        "domain/hardware/external fact, an opinion, or a future plan).\n"
        "(2) stub: a TELEGRAPHIC fragment (symbols, arrows ->, shorthand) capturing the fact, never a "
        "grammatical sentence a writer could paste. Produce one even for an unverifiable domain fact.\n"
        "(3) needs_source: true if the fact is unverifiable BUT reads as a checkable claim (so the human "
        "should be asked for a URL or a source); false if it is clearly an opinion, a plan, or unverifiable "
        "by nature.\n"
        "(4) note: one line — where the code agrees or disagrees, or why it is unverifiable.\n\n"
        "Write JSON {stub, status, needs_source, note} to ./stub_result.json and reply DONE."
    )
    subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )
    p = os.path.join(rundir, "stub_result.json")
    if not os.path.exists(p):
        sys.exit("no stub_result.json produced — check the run room.")
    r = json.load(open(p))
    print("=== STUBIFY RESULT ===")
    print(f"  status: {r.get('status')}   needs_source: {r.get('needs_source')}")
    print(f"  stub: {r.get('stub')}")
    print(f"  note: {r.get('note')}")
    print("  Orchestrator: confirmed -> append stub to ledger_final.md + regen_symbol; contradicted -> raise")
    print("  suspicion to the human (do NOT block); unverifiable+needs_source -> ask for a URL/desc; else trust.")


if __name__ == "__main__":
    main()
