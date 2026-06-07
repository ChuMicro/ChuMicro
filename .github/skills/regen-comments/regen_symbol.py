#!/usr/bin/env python3
"""Refinement loop: regenerate ONE symbol against the (edited) ledger, splice only it into the finished file.

Used for drop-fact / add-fact / edit-fact / fresh roll-the-dice. The orchestrator has already edited
`ledger_final.md`; this re-runs the writer workflow against it (so the new candidates reflect the edit),
then splices ONLY the target symbol from the new merge onto the existing finished file — every other symbol
the human already accepted stays exactly as it was. It also refreshes `runs/run-*.py`, so later cheap
candidate-cycling (`splice_symbol.py` against a run) sees fresh takes. Re-render the report afterward.

Cost note: this re-runs the full 4-pass writer; for a deliberate human edit that is acceptable, and the
cheap path (cycling cached candidates via splice_symbol.py) covers "just give me a different take" with no
generation at all.

Usage: regen_symbol.py <rundir> <voice> <qualname>
"""
import json
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402


def claude_p_workflow(rundir, wf_name):
    return subprocess.run(
        ["claude", "-p",
         f"Use the Workflow tool to run the workflow at ./{wf_name} (call Workflow with scriptPath "
         f"./{wf_name}). Wait for full completion, then reply DONE.",
         "--allowedTools", "Workflow", "Task", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )


def main():
    require_claude()
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    qual = sys.argv[3]
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    if not os.path.exists(final):
        sys.exit("no finished file yet — run phase 2 before refining.")
    voices = json.load(open(os.path.join(SKILL, "voices.json")))["voices"]
    if voice not in voices:
        sys.exit(f"unknown voice {voice!r}")

    # keep the human's accepted file to splice onto; re-run the writer against the (edited) ledger_final.md
    current = os.path.join(rundir, "current.py")
    shutil.copy(final, current)
    src = open(os.path.join(SKILL, "writers_wf.js")).read()
    src = src.replace("__RUNDIR__", rundir).replace("__VOICE_PARA__", voices[voice])
    open(os.path.join(rundir, "writers_wf.js"), "w").write(src)
    claude_p_workflow(rundir, "writers_wf.js")

    newmerged = os.path.join(rundir, "merged.py")
    if not os.path.exists(newmerged):
        sys.exit("writer produced no merged.py")
    # splice ONLY the target symbol from the new merge onto the human's file (guard rejects any code drift)
    subprocess.run(
        [sys.executable, os.path.join(SKILL, "splice_symbol.py"), current, newmerged, qual, final],
        check=True,
    )
    # enforce the mechanical tic bans on the result (mostly the freshly spliced symbol; no-op when clean)
    subprocess.run([sys.executable, os.path.join(SKILL, "polish.py"), rundir, final], check=True)

    print("=== SYMBOL REGENERATED ===")
    print(f"  {qual!r} regenerated against the current ledger; only that symbol changed in {final}")
    print("  candidates refreshed in runs/; re-render the report (render_report.py) to refresh the view.")


if __name__ == "__main__":
    main()
