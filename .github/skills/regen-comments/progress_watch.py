#!/usr/bin/env python3
"""Live progress for a regen-comments run, watching the run room's artifacts (no stream parsing).

A clean-room phase runs as one `claude -p` whose stdout the orchestrator captures, so the session looks
stalled while the Workflow inside churns for minutes. But each stage drops a file into the run room as it
finishes, so those files ARE the progress. Run this in a SECOND terminal while the skill works:

    python3 progress_watch.py <rundir>

It prints each pipeline artifact as it lands, then exits when the final file appears. It reports only files
touched AFTER it starts, so a re-used run room's stale artifacts from an earlier run are ignored.
"""
import glob
import os
import sys
import time

# (glob relative to rundir, human label), in pipeline order
STEPS = [
    ("stripped.py", "stripped the target (mechanical)"),
    ("findings/trap.json", "lens: trap"),
    ("findings/trace.json", "lens: trace"),
    ("findings/naming.json", "lens: naming"),
    ("findings/comments.json", "lens: comments"),
    ("ledger_provisional.md", "ledger written"),
    ("validation.json", "validator ran"),
    ("ledger_final.md", "ledger finalized (picker done)"),
    ("runs/run-1.py", "writer pass 1"),
    ("runs/run-2.py", "writer pass 2"),
    ("runs/run-3.py", "writer pass 3"),
    ("runs/run-4.py", "writer pass 4"),
    ("summary.json", "independent summarizer"),
    ("merged.py", "consolidation merged"),
    ("cut_report.txt", "cut / dedup"),
    ("FINAL_*.py", "DONE: final file ready"),
]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: progress_watch.py <rundir>")
    rundir = os.path.abspath(sys.argv[1])
    start = time.time()
    seen = set()
    # flush every line: stdout is block-buffered when piped to a file/tail, so a live watcher must flush
    print(f"watching {rundir}\n(reports only artifacts touched from now on; Ctrl-C to stop)", flush=True)
    deadline = start + 1800  # 30-minute safety cap
    while time.time() < deadline:
        for rel, label in STEPS:
            if rel in seen:
                continue
            fresh = [m for m in glob.glob(os.path.join(rundir, rel))
                     if os.path.getmtime(m) >= start - 1]
            if fresh:
                seen.add(rel)
                print(f"  [{time.strftime('%H:%M:%S')}] ok  {label}", flush=True)
                if rel.startswith("FINAL"):
                    print("  run complete.", flush=True)
                    return
        time.sleep(2)
    print("  (watch timed out after 30 min)", flush=True)


if __name__ == "__main__":
    main()
