#!/usr/bin/env python3
"""regen-comments — PHASE 2 (write + select + reattach). Runs AFTER the in-session picker has written
`<rundir>/ledger_final.md`.

Runs the writer workflow (the chosen voice, 4 passes + a best-of-4 voice selector) as ONE clean-room
`claude -p` from the run room, copies the selected pass to merged.py, then mechanically reattaches the
preserve lane. Produces the finished file.

Usage: regen_phase2.py <rundir> <voice_key> [--kind <genre>] [--tight | --less]
--tight = summary-only docstrings (1-2 sentences, no body/sections; self-documenting symbols get none).
--less  = tight's summary discipline WITH short Args/Returns/Raises sections (no body paragraphs).
Precondition: <rundir>/ledger_final.md exists (assembled by the orchestrator after the picker).
The genre is read from <rundir>/phase1.json by default; --kind overrides it.
"""
import glob
import json
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.normpath(os.path.join(SKILL, os.pardir, "_shared", "voices"))
sys.path.insert(0, SKILL)
sys.path.insert(0, VOICES_DIR)
from preflight import require_claude  # noqa: E402
from genre import GENRES  # noqa: E402
from voice_sample import load_voice_sample  # noqa: E402


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
    tight = "--tight" in args
    less = "--less" in args
    if tight and less:
        sys.exit("--tight and --less are mutually exclusive; pick one.")
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
    voices = json.load(open(os.path.join(VOICES_DIR, "voices.json")))["voices"]
    if voice not in voices:
        sys.exit(f"unknown voice '{voice}'. Known: {', '.join(voices)} (or add via --create-voice).")
    os.makedirs(os.path.join(rundir, "runs"), exist_ok=True)
    # record the run shape so the refine-loop tools (regen_symbol, tighten_symbol) regenerate in the SAME
    # shape -- without this, a mid-refine regen on a --tight or test/example-genre run silently fell back to
    # the default code shape (the template's __GENRE__/__TIGHT__ placeholders were left unsubstituted)
    json.dump({"voice": voice, "genre": genre, "tight": tight, "less": less},
              open(os.path.join(rundir, "phase2.json"), "w"))

    # writer workflow: chosen voice, 4 passes + best-of-N selector (the selector only emits a winner number)
    src = open(os.path.join(SKILL, "writers_wf.js")).read()
    src = (src.replace("__RUNDIR__", rundir).replace("__VOICE_PARA__", voices[voice])
              .replace('"__VOICE_SAMPLE__"', json.dumps(load_voice_sample(voice)))
              .replace("__GENRE__", genre).replace("__TIGHT__", "1" if tight else "0")
              .replace("__LESS__", "1" if less else "0"))
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
    # strip.py turns a docstring-only body into `pass`; a writer re-adding the docstring keeps that pass
    # often enough that the FINAL gains a stray Pass node the original never had (verify then fails and
    # an applied diff would carry `+ pass`). Normalize every cached pass + the merged copy to the
    # docstring-only form so the splice/roll-the-dice candidates stay code-identical too.
    sys.path.insert(0, SKILL)
    from normalize_stub_pass import normalize  # noqa: E402
    for candidate in glob.glob(os.path.join(rundir, "runs", "run-*.py")) + [merged]:
        if normalize(candidate):
            print(f"  normalized docstring-redundant pass: {os.path.basename(candidate)}")
    print(f"  selected run-{winner}: {pick.get('why', '')}")
    if pick.get("concern"):
        print(f"  selector concern: {pick['concern']}")
    # deterministic auto-route (no LLM): if the winner carries a tic/leak on a symbol but another cached
    # pass has a clean take, splice that take in verbatim (code-identity guarded, recorded in pick.json,
    # surfaced in the report). Runs before polish so routed-in raw text still gets the ban-fix loop.
    subprocess.run([sys.executable, os.path.join(SKILL, "autoroute_tics.py"), rundir, voice, merged],
                   check=False)
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
