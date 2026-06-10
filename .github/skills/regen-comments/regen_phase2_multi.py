#!/usr/bin/env python3
"""Multi-voice: generate the file in up to 3 voices for a side-by-side comparison.

A comparison run scopes up to 3 voices. The writer can't apply three versions to one file, so each voice is
generated in ISOLATION under ``<rundir>/v/<voice>/`` — its own ``runs/``, ``pick.json``, ``FINAL_<voice>.py``,
``legibility.json`` — and the human compares them, then applies ONE. Each per-voice room is a complete run
room: it gets a copy of the shared phase-1 inputs (``stripped.py``, ``ledger_final.md``, ``preserve.json``,
``phase1.json``, and ``LIBRARY_FACTS.md`` if present), and ``regen_phase2.py`` runs there. Because each room is
self-contained, the Step 8 refine tools work on the chosen voice's room unchanged.

Usage: regen_phase2_multi.py <rundir> <voice1> [voice2] [voice3]
Precondition: <rundir>/ledger_final.md exists (assembled by the picker).
"""
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
SHARED_INPUTS = ("stripped.py", "ledger_final.md", "preserve.json", "phase1.json", "LIBRARY_FACTS.md")


def run_voice(rundir, voice):
    """Generate one voice in its own sub-room and report whether its FINAL landed."""
    sub = os.path.join(rundir, "v", voice)
    os.makedirs(sub, exist_ok=True)
    for f in SHARED_INPUTS:                       # copy the shared phase-1 inputs into the per-voice room
        src = os.path.join(rundir, f)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(sub, f))
    r = subprocess.run([sys.executable, os.path.join(SKILL, "regen_phase2.py"), sub, voice] + EXTRA,
                       capture_output=True, text=True)
    final = os.path.join(sub, f"FINAL_{voice}.py")
    return voice, sub, os.path.exists(final), r.returncode, (r.stdout or "")[-400:] + (r.stderr or "")[-300:]


EXTRA = []  # set by main(): ["--tight"] when the run is tight mode


def main():
    rundir = os.path.abspath(sys.argv[1])
    if "--tight" in sys.argv:
        sys.argv.remove("--tight")
        EXTRA.append("--tight")
    voices = sys.argv[2:5]                          # up to 3
    if not 1 <= len(voices) <= 3:
        sys.exit("give 1 to 3 voices: regen_phase2_multi.py <rundir> <voice1> [voice2] [voice3]")
    if len(set(voices)) != len(voices):
        sys.exit(f"duplicate voice in {voices}; pick distinct voices to compare.")
    if not os.path.exists(os.path.join(rundir, "ledger_final.md")):
        sys.exit("ledger_final.md missing — run the picker + assemble it before phase 2.")
    # concurrency 2: each voice is its own 4-pass claude -p fan-out, so 2 at a time avoids oversubscribing
    results = []
    # one wave for up to 3 voices: each voice is ~5 internal agents, so 3 voices ~= 15 concurrent,
    # the same scale regen_batch already sanctions; capping at 2 made a 3-voice run take two waves
    with cf.ThreadPoolExecutor(max_workers=min(3, len(voices))) as ex:
        for res in ex.map(lambda v: run_voice(rundir, v), voices):
            results.append(res)

    print("=== MULTI-VOICE PHASE 2 COMPLETE ===")
    for voice, sub, ok, rc, tail in results:
        print(f"  {voice:14} {'OK ' if ok else 'FAILED'} -> {os.path.join(sub, f'FINAL_{voice}.py')}")
        if not ok:
            print(f"     (exit {rc}) {tail.strip()[-200:]}")
    print("  Next (in-session): verify_code each FINAL, render the comparison "
          "(render_compare.py <rundir> <target.py> <voices...>), then APPLY one voice.")


if __name__ == "__main__":
    main()
