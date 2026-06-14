#!/usr/bin/env python3
"""Run a clean-room `claude -p` workflow with a mechanical completion guard.

The Workflow tool inside the clean-room agent runs its script in the BACKGROUND and returns
immediately; the agent is told to wait for the completion notification, but it can reply DONE
early, and when the `claude -p` subprocess exits it kills the workflow mid-flight (observed
2026-06-10: one writer pass refreshed, pick.json mid-write, three stale passes judged by the
selector). The room's leftover artifacts then satisfy bare existence checks, so the caller
splices stale content and reports success. Completion is therefore verified MECHANICALLY:
every artifact the workflow must produce has to carry an mtime after the launch, and a failed
run gets ONE relaunch (transient `claude -p` blanks are real: 2026-06-10 all five Generate
agents produced nothing once) before a loud halt.
"""
import json
import os
import shutil
import subprocess
import sys
import time

SKILL = os.path.dirname(os.path.abspath(__file__))

# every artifact the writer workflow (writers_wf.js, PASSES=4) must produce
WRITER_ARTIFACTS = ("runs/run-1.py", "runs/run-2.py", "runs/run-3.py", "runs/run-4.py",
                    "summary.json", "pick.json")


def run_workflow(rundir, wf_name, required=(), retries=1, marker=None):
    """One clean-room `claude -p` running the staged workflow; halt unless `required` are all fresh.

    `marker` names the LAST artifact the workflow writes (pick.json for the writer flow). It is deleted
    before each launch so the agent can poll it honestly: the clean-room agent has no tool that waits
    (Workflow returns immediately, and ending its turn exits `claude -p`, killing the background run), so
    without a poll target the run only survives when the completion notification happens to arrive first.
    """
    if marker:
        prompt = (f"Use the Workflow tool to run the workflow at ./{wf_name} (call Workflow with scriptPath "
                  f"./{wf_name}). It runs in the BACKGROUND and the tool returns immediately -- launching it "
                  f"is not finishing it, and if you stop responding the workflow is killed. Its FINAL step "
                  f"writes ./{marker}, which does not exist right now. After launching, poll by Read-ing "
                  f"./{marker}; a missing-file error means it is still running, so Read it again (keep "
                  f"polling indefinitely -- a writer pass takes minutes). Only when ./{marker} exists and "
                  f"holds content, reply DONE.")
    else:
        prompt = (f"Use the Workflow tool to run the workflow at ./{wf_name} (call Workflow with scriptPath "
                  f"./{wf_name}). The Workflow tool runs it in the background and returns immediately; do "
                  f"NOT stop after launching it. Wait until the workflow completion notification arrives, "
                  f"then reply DONE.")
    stale = []
    for attempt in range(1 + retries):
        # remove the prior run's artifacts before launching, not just the marker. A stale marker would
        # satisfy the poll instantly, and a stale run-N.py trips the Write tool's read-before-write guard
        # inside the workflow -- writer agents that don't recover with a Read reply "DONE, wrote it"
        # without having written anything (observed 2026-06-10 in every refine-room writer).
        for prior in set(required) | ({marker} if marker else set()):
            p = os.path.join(rundir, prior)
            if os.path.exists(p):
                os.remove(p)
        start = time.time()
        subprocess.run(
            ["claude", "-p", prompt, "--setting-sources", "project,local", "--strict-mcp-config",
             "--disable-slash-commands", "--allowedTools", "Workflow", "Task", "Read", "Write",
             "--permission-mode", "acceptEdits", "--model", "opus"],
            cwd=rundir, capture_output=True, text=True,
            env={**os.environ, "CLAUDE_CODE_WORKFLOWS": "1"},
        )
        # mtime, not existence: a prior run's leftovers satisfy existence and poison the result
        stale = [p for p in required
                 if not os.path.exists(os.path.join(rundir, p))
                 or os.path.getmtime(os.path.join(rundir, p)) < start - 2]
        if not stale:
            return
        more = attempt < retries
        print(f"  workflow {wf_name} incomplete: {', '.join(stale)} stale or missing"
              + ("; relaunching once..." if more else ""), flush=True)
    sys.exit(f"writer workflow still incomplete after relaunch ({', '.join(stale)} stale/missing in "
             f"{rundir}) — the clean-room agent likely exited before the workflow finished; inspect the "
             f"room's transcript and re-run.")


def copy_winner(rundir):
    """Copy the selector's chosen pass to merged.py verbatim; normalize stub-pass on every candidate.

    The copy — not an agent — makes merged.py byte-identical to the chosen pass, so no agent rewrite can
    slip a reworded inversion through. Returns the parsed pick.json. Normalizing the cached passes too
    keeps later candidate-cycling (splice_symbol.py against a run) code-identical to the original.
    """
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
    sys.path.insert(0, SKILL)
    import glob as _glob

    from normalize_stub_pass import normalize  # noqa: E402  (lazy: keeps this module import-light)
    for candidate in _glob.glob(os.path.join(rundir, "runs", "run-*.py")) + [merged]:
        if normalize(candidate):
            print(f"  normalized docstring-redundant pass: {os.path.basename(candidate)}")
    return pick
