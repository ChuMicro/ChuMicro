#!/usr/bin/env python3
"""regen-comments — PHASE 2 (write + consolidate + reattach). Runs AFTER the in-session picker has written
`<rundir>/ledger_final.md`.

Runs the writer workflow (the chosen voice, 4 passes + per-symbol consolidation) as ONE clean-room
`claude -p` from the run room, then mechanically reattaches the preserve lane. Produces the finished file.

Usage: regen_phase2.py <rundir> <voice_key>
Precondition: <rundir>/ledger_final.md exists (assembled by the orchestrator after the picker).
"""
import json
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))


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
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    if not os.path.exists(os.path.join(rundir, "ledger_final.md")):
        sys.exit("ledger_final.md missing — run the picker + assemble it before phase 2.")
    voices = json.load(open(os.path.join(SKILL, "voices.json")))["voices"]
    if voice not in voices:
        sys.exit(f"unknown voice '{voice}'. Known: {', '.join(voices)} (or add via --create-voice).")
    os.makedirs(os.path.join(rundir, "runs"), exist_ok=True)

    # writer workflow: chosen voice, 4 passes + per-symbol consolidation
    src = open(os.path.join(SKILL, "writers_wf.js")).read()
    src = src.replace("__RUNDIR__", rundir).replace("__VOICE_PARA__", voices[voice])
    open(os.path.join(rundir, "writers_wf.js"), "w").write(src)
    claude_p_workflow(rundir, "writers_wf.js")

    merged = os.path.join(rundir, "merged.py")
    if not os.path.exists(merged):
        sys.exit("writer phase produced no merged.py — check the run room.")
    # Step 5 (verify): enforce the mechanical tic bans before reattach (no-op when already clean)
    subprocess.run([sys.executable, os.path.join(SKILL, "polish.py"), rundir, merged], check=True)
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    preserve = os.path.join(rundir, "preserve.json")
    # reattach only if there is a preserve lane; otherwise the merged file is already final
    if os.path.exists(preserve) and json.load(open(preserve)):
        subprocess.run([sys.executable, os.path.join(SKILL, "reattach.py"), merged, preserve, final], check=True)
    else:
        shutil.copy(merged, final)

    print("=== PHASE 2 COMPLETE ===")
    print(f"  finished file: {final}")
    print("  Present it for the human's final review. Do NOT auto-commit / auto-apply.")


if __name__ == "__main__":
    main()
