#!/usr/bin/env python3
"""Live progress for regen-comments runs, watching run-room artifacts (no stream parsing).

A clean-room phase runs as one `claude -p` that prints nothing until it finishes. But each stage drops a file
into the run room as it completes, so those files ARE the progress. The orchestrator runs the phase in the
background and arms a Monitor on this script — each line printed below becomes a chat event — so progress
streams into the session with no second terminal. A human can also run it directly.

Watches ANY number of rooms (a library batch runs one room per file; pass them all — a single watcher on one
room misses the other files' events entirely). Events are prefixed with the room's tag. Exits when EVERY room
has produced the terminal artifact:

    progress_watch.py <rundir> [<rundir> ...] [--until <glob>]

--until defaults to FINAL_*.py (a phase-2 / full-run watch). For a batch phase-1 watch pass
`--until phase1.json` — without it a phase-1 watch has no terminal artifact and idles to the deadline.
Comparison runs: pass the voice rooms (`$RUN/v/<voice>`) as the rooms. Reports only files touched AFTER the
watch starts, so a re-used room's stale artifacts are ignored.
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
    ("phase1.json", "phase 1 grounding complete"),
    ("ledger_final.md", "ledger finalized (picker done)"),
    ("runs/run-1.py", "writer pass 1"),
    ("runs/run-2.py", "writer pass 2"),
    ("runs/run-3.py", "writer pass 3"),
    ("runs/run-4.py", "writer pass 4"),
    ("summary.json", "independent summarizer"),
    ("pick.json", "selector picked best of N files"),
    ("merged.py", "chosen file copied"),
    ("FINAL_*.py", "DONE: final file ready"),
]


def main():
    args = sys.argv[1:]
    until = "FINAL_*.py"
    if "--until" in args:
        i = args.index("--until")
        until = args[i + 1]
        del args[i:i + 2]
    rooms = [os.path.abspath(a) for a in args]
    if not rooms:
        sys.exit("usage: progress_watch.py <rundir> [<rundir> ...] [--until <glob>]")

    start = time.time()
    seen = set()           # (room, rel) pairs already reported
    done = set()           # rooms whose terminal artifact landed
    tags = {r: os.path.basename(r) for r in rooms}
    # flush every line: stdout is block-buffered when piped, so a live watcher must flush
    print(f"watching {len(rooms)} room(s), until {until!r} in each "
          f"(reports only artifacts touched from now on; Ctrl-C to stop)", flush=True)
    for r in rooms:
        print(f"  - {tags[r]}", flush=True)
    deadline = start + 7200  # safety cap; long comparison/library runs legitimately take over an hour
    while time.time() < deadline:
        for room in rooms:
            for rel, label in STEPS:
                key = (room, rel)
                if key in seen:
                    continue
                fresh = [m for m in glob.glob(os.path.join(room, rel))
                         if os.path.getmtime(m) >= start - 1]
                if fresh:
                    seen.add(key)
                    print(f"  [{time.strftime('%H:%M:%S')}] {tags[room]}: {label}", flush=True)
            if room not in done:
                hit = [m for m in glob.glob(os.path.join(room, until))
                       if os.path.getmtime(m) >= start - 1]
                if hit:
                    done.add(room)
                    print(f"  [{time.strftime('%H:%M:%S')}] {tags[room]}: reached {until} "
                          f"({len(done)}/{len(rooms)} rooms done)", flush=True)
        if len(done) == len(rooms):
            print("  all rooms complete.", flush=True)
            return
        time.sleep(2)
    print("  (watch timed out after 2 h)", flush=True)


if __name__ == "__main__":
    main()
