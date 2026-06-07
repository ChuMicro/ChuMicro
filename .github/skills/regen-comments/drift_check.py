#!/usr/bin/env python3
"""Refinement loop: after a ledger edit + symbol regen, flag OTHER symbols whose comments went stale.

Runs one clean-room `claude -p` that reads the current finished file and the stripped code, and checks
whether the change just made left any OTHER symbol's docstring/comments contradictory or stale. Conservative
by design: it lists a symbol ONLY when sure, so the orchestrator can offer to clean those up too without
nagging about speculation. Writes `<rundir>/drift.json` = {drifted:[{symbol, why}]}.

Usage: drift_check.py <rundir> <voice> <changed_symbol> "<what changed>"
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
    sym = sys.argv[3]
    change = sys.argv[4]
    final = f"FINAL_{voice}.py"
    prompt = (
        "A ledger fact was just changed and one symbol was regenerated. Check whether the change left any "
        "OTHER symbol's docstring/comments CONTRADICTORY or STALE.\n\n"
        "FINISHED FILE: ./" + final + "\nCODE (truth): ./stripped.py\n"
        "CHANGED SYMBOL: " + sym + "\nWHAT CHANGED: " + change + "\n\n"
        "Be conservative. List a symbol ONLY if you are SURE its existing comment is now WRONG or STALE "
        "because of this change — not for style, not for speculation, not for 'could be clearer'. If nothing "
        "is surely affected, return an empty list.\n\n"
        "Write JSON {drifted:[{symbol, why}]} to ./drift.json and reply DONE."
    )
    subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )
    p = os.path.join(rundir, "drift.json")
    d = json.load(open(p)).get("drifted", []) if os.path.exists(p) else []
    print("=== DRIFT CHECK ===")
    if not d:
        print("  no other symbols surely affected by the change.")
        return
    print(f"  {len(d)} symbol(s) may now be stale because of the change:")
    for it in d:
        print(f"    - {it.get('symbol')}: {it.get('why')}")
    print("  Orchestrator: offer to regen these too (regen_symbol.py), even though the human picked one symbol.")


if __name__ == "__main__":
    main()
