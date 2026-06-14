#!/usr/bin/env python3
"""Refinement loop: shorten ONE symbol's docstring WITHOUT losing facts (the fact-preserving 'tighten').

A blunt body-drop is destructive — it discards must-carry facts (e.g. a by-reference safety note the human
kept in the picker). This instead runs a clean-room `claude -p` that rewrites only the target symbol's
docstring shorter and denser: it keeps the lead sentence, the Args/Returns/Raises sections, the voice, and
EVERY ledger fact that pertains to the symbol, cutting only wordy prose that merely restates. It splices
just that symbol back (code-identity guarded), re-polishes, and prints a KEPT/DROPPED fact report so the
orchestrator can push back before Apply if a kept fact would be lost.

Usage: tighten_symbol.py <rundir> <voice> <qualname>
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
    qual = sys.argv[3]
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    if not os.path.exists(final):
        sys.exit("no finished file yet — run phase 2 before tightening.")
    # announce before the silent clean-room call so a chained refine sequence self-narrates
    print(f"tightening {qual!r}, fact-preserving (one clean-room claude -p, ~1 min)...", flush=True)
    # a --tight run has no sections to keep (telling the agent to KEEP Args/Returns there would re-grow
    # them); a --less run keeps the sections but its summary must stay at 1-2 sentences
    p2 = os.path.join(rundir, "phase2.json")
    cfg = json.load(open(p2)) if os.path.exists(p2) else {}
    if cfg.get("tight"):
        keep_sections = "at most 1-2 short sentences and NO Args/Returns/Raises sections (this run is in tight mode)"
    elif cfg.get("less"):
        keep_sections = ("the Args/Returns/Raises sections, with the summary staying at most 1-2 short "
                         "sentences and no body paragraphs (this run is in less mode)")
    else:
        keep_sections = "the Args/Returns/Raises sections"

    prompt = (
        "Read ./FINAL_" + voice + ".py and the nuance ledger ./ledger_final.md. Produce a copy of the file "
        "where ONLY the symbol " + qual + " has its docstring TIGHTENED, written to ./tightened.py.\n"
        "Tighten = shorter and denser. KEEP: the lead sentence (and any sentence carrying a non-obvious "
        "fact), " + keep_sections + ", the voice, and EVERY ledger fact that pertains to " + qual
        + " (including non-derivable / domain facts). CUT only wordy prose that merely restates the lead "
        "sentence or the Args, or padding about what the code does NOT do. Do NOT add facts. Do NOT "
        "change any executable code or any other symbol -- copy them verbatim.\n"
        "Also write ./tighten_report.txt with two labelled lists: 'KEPT:' (the facts you preserved) and "
        "'DROPPED:' (anything you could NOT keep while shortening -- empty if none). Reply DONE after both "
        "files exist.\n"
    )
    # clear the previous round's outputs so the existence check below can't pass on a stale file when the
    # agent produces nothing (same stale-artifact family as the regen_symbol merge bug, 2026-06-10)
    tightened = os.path.join(rundir, "tightened.py")
    for prior in (tightened, os.path.join(rundir, "tighten_report.txt")):
        if os.path.exists(prior):
            os.remove(prior)
    subprocess.run(
        ["claude", "-p", prompt, "--setting-sources", "project,local", "--strict-mcp-config",
         "--disable-slash-commands", "--allowedTools", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )
    if not os.path.exists(tightened):
        sys.exit("tighten produced no tightened.py — check the run room.")

    # splice ONLY the target symbol from the tightened copy (guard rejects any code drift), then re-polish
    subprocess.run(
        [sys.executable, os.path.join(SKILL, "splice_symbol.py"), final, tightened, qual, final],
        check=True,
    )
    subprocess.run([sys.executable, os.path.join(SKILL, "polish.py"), rundir, final], check=True)

    print("=== TIGHTENED ===")
    print(f"  {qual!r} tightened in {final} (only that symbol changed; code byte-identical)")
    rep = os.path.join(rundir, "tighten_report.txt")
    if os.path.exists(rep):
        print("  --- tighten report (kept / dropped facts) ---")
        for line in open(rep).read().strip().splitlines():
            print("   " + line)
    print("  Orchestrator: if the report lists DROPPED facts, surface them and confirm with the human before Apply.")


if __name__ == "__main__":
    main()
