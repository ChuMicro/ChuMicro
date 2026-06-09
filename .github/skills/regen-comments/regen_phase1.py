#!/usr/bin/env python3
"""regen-comments — PHASE 1 (grounding). Mechanical + clean-room triage, no human gate.

Strips the target, captures its header for preservation, sets up a /tmp run room, then runs the triage
workflow as ONE `claude -p` from the room (clean: no project CLAUDE.md by cwd-ancestry, file access bounded
to the room). The workflow now folds the fixture-agnostic validator and its ledger-writer re-run loop in,
so phase 1 is a single `claude -p`. It then collects the outputs the in-session orchestrator needs:
  - ledger_provisional.md   (the telegraphic ledger)
  - ledger.json             (structured facts + confidence + source lenses)
  - preserve.json           (mechanical header + the comment lens's preserve lane, for reattach in phase 2)
  - validation.json         (the fixture-agnostic gate: any_wrong / any_underspecified)
  - phase1.json             (questionable facts for the picker + needs_user escalation flag)

The PICKER (AskUserQuestion) and the assembly of ledger_final.md happen IN-SESSION, between phase 1 and
phase 2 — a headless subprocess cannot ask the user anything.

Usage: regen_phase1.py <target.py> <rundir> [--without-comment-triage] [--lib <LIBRARY_FACTS.md>]
"""
import json
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from strip import extract_header  # noqa: E402  (always-on mechanical header preservation)
from preflight import require_claude  # noqa: E402
from genre import detect_genre, GENRES  # noqa: E402


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
    require_claude()
    args = sys.argv[1:]
    with_comments = "--without-comment-triage" not in args  # comment-triage is ON by default
    lib = args[args.index("--lib") + 1] if "--lib" in args else None
    kind = args[args.index("--kind") + 1] if "--kind" in args else None
    flag_vals = {v for v in (lib, kind) if v is not None}
    pos = [a for a in args if not a.startswith("--") and a not in flag_vals]
    target, rundir = pos[0], pos[1]
    # genre selects the triage aim + writer shape; default by path convention, override with --kind
    genre = kind or detect_genre(target)
    if genre not in GENRES:
        sys.exit(f"unknown --kind '{genre}'. Known: {', '.join(GENRES)}.")
    rundir = os.path.abspath(rundir)
    # Freshness guard: phase 1 must start in a fresh room. A room already holding a prior run's outputs
    # (phase1.json or a FINAL_*.py) means two runs collided or a stale dir is being reused -- both poison
    # the result. Allocate a fresh room with rooms.py instead of reusing one.
    if os.path.isdir(rundir):
        existing = os.listdir(rundir)
        if "phase1.json" in existing or any(f.startswith("FINAL_") for f in existing):
            sys.exit(f"run room {rundir} already holds a prior run's artifacts; allocate a FRESH room "
                     f"(RUN=$(python3 {SKILL}/rooms.py new <slug>)) so parallel or stale runs can't collide.")
    os.makedirs(os.path.join(rundir, "findings"), exist_ok=True)

    # 0. strip (mechanical)
    subprocess.run([sys.executable, os.path.join(SKILL, "strip.py"), target,
                    os.path.join(rundir, "stripped.py")], check=True)
    # the comment lens always runs; with comment-triage ON (default) it sees the real comments, with
    # --without-comment-triage it sees the stripped file (no comments -> empty ledger lane). Either way the
    # writers are clean-room, and header preservation below is mechanical and independent of this choice.
    shutil.copy(target if with_comments else os.path.join(rundir, "stripped.py"),
                os.path.join(rundir, "commented.py"))
    if lib:
        shutil.copy(lib, os.path.join(rundir, "LIBRARY_FACTS.md"))

    # 1. triage workflow (3 code lenses + comment lens + ledger-writer + validate/converge loop), one
    #    clean-room claude -p. The validator and its ledger-writer-retry loop live inside the workflow.
    _stage("triage_wf.js", rundir, __RUNDIR__=rundir, __GENRE__=genre)
    claude_p_workflow(rundir, "triage_wf.js")

    # 3. collect for the picker
    def _load(p, default):
        fp = os.path.join(rundir, p)
        return json.load(open(fp)) if os.path.exists(fp) else default

    ledger = _load("ledger.json", [])
    comments = _load(os.path.join("findings", "comments.json"), {})
    val = _load("validation.json", {})
    # preserve lane: the mechanical header (copyright/license/author) is ALWAYS captured, regardless of
    # comment-triage mode, so a license header is never silently lost. The comment lens's preserve items
    # (inline TODOs, plus any header it also flagged) merge in, deduped by line text so nothing doubles.
    header = extract_header(open(target).read())
    header_lines = {h["line"].strip() for h in header}
    clens = comments.get("preserve", []) if isinstance(comments, dict) else []
    extra = [p for p in clens if p.get("line", "").strip() not in header_lines]
    preserve = header + extra
    json.dump(preserve, open(os.path.join(rundir, "preserve.json"), "w"), indent=2)
    # questionable = low/med confidence only. High-confidence facts are auto-kept whether code- OR
    # comment-derived: a confident fact does not need a human keep/drop, and surfacing them all made the
    # picker too involved. Low/med comment-derived facts still surface (they ARE low/med).
    questionable = [f for f in ledger if f.get("confidence") in ("low", "med")]
    needs_user = bool(val.get("any_wrong") or val.get("any_underspecified"))
    json.dump({"genre": genre, "questionable": questionable, "validation": val, "needs_user": needs_user,
               "ledger_provisional": os.path.join(rundir, "ledger_provisional.md"),
               "preserve_json": os.path.join(rundir, "preserve.json")},
              open(os.path.join(rundir, "phase1.json"), "w"), indent=2)

    print("=== PHASE 1 COMPLETE ===")
    print(f"  rundir: {rundir}   genre: {genre}")
    print(f"  ledger facts: {len(ledger)}   preserve lane: {len(preserve)}")
    print(f"  validator: any_wrong={val.get('any_wrong')} any_underspecified={val.get('any_underspecified')}")
    if needs_user:
        print("  >>> validator STILL flags issues after the in-workflow ledger-writer retry loop; the "
              "orchestrator must ESCALATE — present the flagged facts (validation.json) plus a recommendation "
              "in an AskUserQuestion with a free-text window before phase 2.")
    print(f"  QUESTIONABLE facts for the picker ({len(questionable)}):")
    for i, f in enumerate(questionable):
        print(f"    [{i}] ({f.get('confidence')}, {','.join(f.get('source_lenses', []))}) {f.get('stub', '')[:120]}")
    print("  Next (in-session): run the picker on these, write ledger_final.md = ledger_provisional.md "
          "minus the rejected facts, then run regen_phase2.py.")


if __name__ == "__main__":
    main()
