#!/usr/bin/env python3
"""regen-comments — PHASE 1 (grounding). Mechanical + clean-room triage, no human gate.

Strips the target, sets up a /tmp run room, runs the triage workflow and the ledger validator each as ONE
`claude -p` from the room (clean: no project CLAUDE.md by cwd-ancestry, file access bounded to the room),
then collects the outputs the in-session orchestrator needs for the picker:
  - ledger_provisional.md   (the telegraphic ledger)
  - ledger.json             (structured facts + confidence + source lenses)
  - preserve.json           (the comment lens's preserve lane, for reattach in phase 2)
  - validation.json         (the fixture-agnostic gate: any_wrong / any_underspecified)
  - phase1.json             (questionable facts for the picker + validation summary)

The PICKER (AskUserQuestion) and the assembly of ledger_final.md happen IN-SESSION, between phase 1 and
phase 2 — a headless subprocess cannot ask the user anything.

Usage: regen_phase1.py <target.py> <rundir> [--with-comment-triage] [--lib <LIBRARY_FACTS.md>]
"""
import json
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))


def claude_p_workflow(rundir, wf_name):
    """Run one clean-room `claude -p` from rundir that executes the named workflow to completion."""
    return subprocess.run(
        ["claude", "-p",
         f"Use the Workflow tool to run the workflow at ./{wf_name} (call Workflow with scriptPath "
         f"./{wf_name}). Wait for full completion, then reply DONE.",
         "--allowedTools", "Workflow", "Task", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )


def _stage(wf_src, rundir, **subs):
    src = open(os.path.join(SKILL, wf_src)).read()
    for k, v in subs.items():
        src = src.replace(k, v)
    open(os.path.join(rundir, wf_src), "w").write(src)


def main():
    args = sys.argv[1:]
    with_comments = "--with-comment-triage" in args
    lib = args[args.index("--lib") + 1] if "--lib" in args else None
    pos = [a for i, a in enumerate(args)
           if not a.startswith("--") and (lib is None or a != lib)]
    target, rundir = pos[0], pos[1]
    rundir = os.path.abspath(rundir)
    os.makedirs(os.path.join(rundir, "findings"), exist_ok=True)

    # 0. strip (mechanical)
    subprocess.run([sys.executable, os.path.join(SKILL, "strip.py"), target,
                    os.path.join(rundir, "stripped.py")], check=True)
    # the comment lens always runs; in --with-comment-triage it sees the real comments, otherwise it sees
    # the stripped file (no comments -> empty ledger lane). The writers are clean-room either way.
    shutil.copy(target if with_comments else os.path.join(rundir, "stripped.py"),
                os.path.join(rundir, "commented.py"))
    if lib:
        shutil.copy(lib, os.path.join(rundir, "LIBRARY_FACTS.md"))

    # 1. triage workflow (3 code lenses + comment lens + ledger-writer), one clean-room claude -p
    _stage("triage_wf.js", rundir, __RUNDIR__=rundir)
    claude_p_workflow(rundir, "triage_wf.js")
    # 2. ledger validator (fixture-agnostic), one clean-room claude -p
    _stage("ledger_validate.js", rundir, __RUNDIR__=rundir)
    claude_p_workflow(rundir, "ledger_validate.js")

    # 3. collect for the picker
    def _load(p, default):
        fp = os.path.join(rundir, p)
        return json.load(open(fp)) if os.path.exists(fp) else default

    ledger = _load("ledger.json", [])
    comments = _load(os.path.join("findings", "comments.json"), {})
    val = _load("validation.json", {})
    preserve = comments.get("preserve", []) if isinstance(comments, dict) else []
    json.dump(preserve, open(os.path.join(rundir, "preserve.json"), "w"), indent=2)
    # questionable = low/med confidence OR comment-derived (a human decides whether each reaches the writers)
    questionable = [f for f in ledger
                    if f.get("confidence") in ("low", "med")
                    or any("comment" in s for s in f.get("source_lenses", []))]
    json.dump({"questionable": questionable, "validation": val,
               "ledger_provisional": os.path.join(rundir, "ledger_provisional.md"),
               "preserve_json": os.path.join(rundir, "preserve.json")},
              open(os.path.join(rundir, "phase1.json"), "w"), indent=2)

    print("=== PHASE 1 COMPLETE ===")
    print(f"  rundir: {rundir}")
    print(f"  ledger facts: {len(ledger)}   preserve lane: {len(preserve)}")
    print(f"  validator: any_wrong={val.get('any_wrong')} any_underspecified={val.get('any_underspecified')}")
    if val.get("any_wrong") or val.get("any_underspecified"):
        print("  >>> validator flagged issues; the orchestrator should re-run the ledger-writer with the "
              "validator notes before phase 2 (see validation.json).")
    print(f"  QUESTIONABLE facts for the picker ({len(questionable)}):")
    for i, f in enumerate(questionable):
        print(f"    [{i}] ({f.get('confidence')}, {','.join(f.get('source_lenses', []))}) {f.get('stub', '')[:120]}")
    print("  Next (in-session): run the picker on these, write ledger_final.md = ledger_provisional.md "
          "minus the rejected facts, then run regen_phase2.py.")


if __name__ == "__main__":
    main()
