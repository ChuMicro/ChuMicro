#!/usr/bin/env python3
"""Live progress for audit-code runs, watching run-room artifacts (no stream parsing).

The evaluation runs as one `claude -p` that prints nothing until it finishes, but its stages drop files
into the run room as they complete — those files ARE the progress. The orchestrator launches the phase in
the background and arms a Monitor on this script; each line printed becomes a chat event, so progress
streams into the session with no second terminal. A human can also run it directly.

Watches ANY number of rooms (library/folder mode runs one room per file; pass them all — a single watcher
misses every other file's events). Events are prefixed with the room's tag. Exits when EVERY room has
produced the terminal artifact:

    progress_watch.py <rundir> [<rundir> ...] [--until <glob>]

--until defaults to phase1.json (the evaluation's last write). For a phase-0 library-triage watch pass the
LIBROOM with `--until LIBRARY_FACTS.md`. Reports only files touched AFTER the watch starts, so a re-used
room's stale artifacts are ignored.
"""
import glob
import os
import sys
import time

# (glob relative to rundir, human label), in pipeline order
STEPS = [
    ("lib", "library source stripped + laid out (phase 0, mechanical)"),
    ("LIBRARY_FACTS.md", "library triage complete (phase 0)"),
    ("stripped.py", "stripped the target (mechanical)"),
    ("tests.py", "tests located + concatenated"),
    ("commented.py", "commented copy staged for the drift lens"),
    ("findings/*.json", "lens findings landing"),
    ("summary.json", "independent summarizer"),
    ("eval.json", "merger: numbered fact ledger written"),
    ("validation.json", "validator ran"),
    ("patches.json", "patcher: apply-ready before/after per finding"),
    ("written.json", "reader prose written"),
    ("phase1.json", "DONE: evaluation complete"),
]


def main():
    args = sys.argv[1:]
    until = "phase1.json"
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
    deadline = start + 7200  # safety cap; library runs legitimately take over an hour
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
