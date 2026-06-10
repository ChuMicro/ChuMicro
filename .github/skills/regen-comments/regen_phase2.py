#!/usr/bin/env python3
"""regen-comments — PHASE 2 (write + select + reattach). Runs AFTER the in-session picker has written
`<rundir>/ledger_final.md`.

Runs the writer workflow (the chosen voice, 4 passes + a best-of-4 voice selector) as ONE clean-room
`claude -p` from the run room, copies the selected pass to merged.py, then mechanically reattaches the
preserve lane. Produces the finished file.

Usage: regen_phase2.py <rundir> <voice_key> [--kind <genre>]
Precondition: <rundir>/ledger_final.md exists (assembled by the orchestrator after the picker).
The genre is read from <rundir>/phase1.json by default; --kind overrides it.
"""
import json
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402
from genre import GENRES  # noqa: E402


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
    args = sys.argv[1:]
    kind = args[args.index("--kind") + 1] if "--kind" in args else None
    pos = [a for a in args if not a.startswith("--") and a != kind]
    rundir = os.path.abspath(pos[0])
    voice = pos[1]
    # genre selects the writer shape; phase 1 recorded it in phase1.json, --kind overrides
    p1 = os.path.join(rundir, "phase1.json")
    genre = kind or (json.load(open(p1)).get("genre") if os.path.exists(p1) else None) or "code"
    if genre not in GENRES:
        sys.exit(f"unknown --kind '{genre}'. Known: {', '.join(GENRES)}.")
    if not os.path.exists(os.path.join(rundir, "ledger_final.md")):
        sys.exit("ledger_final.md missing — run the picker + assemble it before phase 2.")
    voices = json.load(open(os.path.join(SKILL, "voices.json")))["voices"]
    if voice not in voices:
        sys.exit(f"unknown voice '{voice}'. Known: {', '.join(voices)} (or add via --create-voice).")
    os.makedirs(os.path.join(rundir, "runs"), exist_ok=True)

    # writer workflow: chosen voice, 4 passes + best-of-N selector (the selector only emits a winner number)
    src = open(os.path.join(SKILL, "writers_wf.js")).read()
    src = (src.replace("__RUNDIR__", rundir).replace("__VOICE_PARA__", voices[voice])
              .replace("__GENRE__", genre))
    open(os.path.join(rundir, "writers_wf.js"), "w").write(src)
    claude_p_workflow(rundir, "writers_wf.js")

    # The selector picked one whole file by number; copy it here in Python. The copy — not the agent — makes
    # merged.py byte-identical to the chosen pass, so no agent rewrite can slip a reworded inversion through.
    pick_path = os.path.join(rundir, "pick.json")
    if not os.path.exists(pick_path):
        sys.exit("writer phase produced no pick.json — check the run room.")
    pick = json.load(open(pick_path))
    winner = pick.get("winner")
    win_file = os.path.join(rundir, "runs", f"run-{winner}.py")
    if not isinstance(winner, int) or not os.path.exists(win_file):
        sys.exit(f"selector returned an invalid winner ({winner!r}); no runs/run-{winner}.py to copy.")
    merged = os.path.join(rundir, "merged.py")
    shutil.copy(win_file, merged)
    print(f"  selected run-{winner}: {pick.get('why', '')}")
    if pick.get("concern"):
        print(f"  selector concern: {pick['concern']}")
    # verify: enforce the mechanical tic bans before reattach (no-op when already clean)
    # (the cut/dedup pass was dropped: an ~8-min LLM call to delete the rare duplicate sentence is not worth
    # it; the writer states each fact once, and a rare slip is minor cosmetic redundancy caught in review)
    subprocess.run([sys.executable, os.path.join(SKILL, "polish.py"), rundir, merged], check=True)
    final = os.path.join(rundir, f"FINAL_{voice}.py")
    preserve = os.path.join(rundir, "preserve.json")
    # reattach only if there is a preserve lane; otherwise the merged file is already final
    if os.path.exists(preserve) and json.load(open(preserve)):
        subprocess.run([sys.executable, os.path.join(SKILL, "reattach.py"), merged, preserve, final], check=True)
    else:
        shutil.copy(merged, final)

    # legibility watcher: flag (never rewrite) any sentence that reads awkwardly, so the rare convoluted roll
    # surfaces in the report for the human to fix in the refine loop instead of shipping silently
    subprocess.run([sys.executable, os.path.join(SKILL, "flag_legibility.py"), rundir, voice], check=False)
    # deterministic flag-only pass (no LLM): AI discourse-marker tics + voice-descriptor leaks, surfaced in
    # the report next to the legibility flags for the human to cut in the refine loop
    subprocess.run([sys.executable, os.path.join(SKILL, "flag_tics.py"), rundir, voice], check=False)

    print("=== PHASE 2 COMPLETE ===")
    print(f"  finished file: {final}   genre: {genre}")
    print("  Present it for the human's final review. Do NOT auto-commit / auto-apply.")


if __name__ == "__main__":
    main()
