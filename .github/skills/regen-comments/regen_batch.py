#!/usr/bin/env python3
"""Bounded-parallel runner for the gate-free phases across many files (library-mode speedup).

Within one file the work is already parallel (the lenses fan out, the 4 writer passes fan out), and
phase1 -> phase2 is inherently sequential (phase 2 needs the human-picked ledger). Across files in library
mode the GATE-FREE phases have no human step, so they run concurrently. This runs phase 1 (grounding) or
phase 2 (writing) for a list of files/rooms with a bounded number of concurrent `claude -p` pipelines.

Each pipeline is its own `claude -p` with its own internal fan-out, so concurrency MULTIPLIES the agent
load — keep it low (2-3) to avoid oversubscribing the API. The human pickers between phase 1 and phase 2
stay sequential and in-session: batch phase 1 for all files, do the pickers, then batch phase 2.

Usage:
  regen_batch.py phase1 <concurrency> [--lib <LIBRARY_FACTS.md>] [--kind <genre>] <file1.py> <file2.py> ...
  regen_batch.py phase2 <concurrency> <voice> <rundir1> <rundir2> ...

--kind sets the genre for every file in the batch (code | test | functional_test | example); omit it and
each file detects its genre from its own path. Phase 2 reads the genre back from each room's phase1.json, so
it takes no --kind. phase1 writes /tmp/regen-cr/batch_manifest.json mapping each file to its run room (the
orchestrator reads it to drive the pickers + phase 2). For --all (whole library), the orchestrator runs one
batch per lane (source/test/functional_test/example), reading each lane's manifest before the next overwrites it.
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402
from rooms import new_room  # noqa: E402

BASE = "/tmp/regen-cr"


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return cmd, r.returncode, r.stdout, r.stderr


def _run_jobs(jobs, concurrency):
    with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futs = [ex.submit(_run, c) for c in jobs]
        for fut in cf.as_completed(futs):
            cmd, rc, out, err = fut.result()
            tag = os.path.basename(cmd[2]) if len(cmd) > 2 else "?"
            print(f"--- {tag}: exit {rc} ---")
            for line in (out.strip().splitlines()[-6:] if out else []):
                print("   ", line)
            if rc != 0 and err:
                print("    STDERR:", " ".join(err.strip().splitlines()[-3:]))


def phase1(argv):
    concurrency = int(argv[0])
    rest = argv[1:]
    lib = kind = None
    while rest and rest[0] in ("--lib", "--kind"):
        if rest[0] == "--lib":
            lib, rest = rest[1], rest[2:]
        else:
            kind, rest = rest[1], rest[2:]
    files = rest
    jobs, manifest = [], {}
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        # mkdtemp a FRESH unique room per file so parallel files (and re-runs) never collide; the genre
        # prefix keeps an --all run's four lanes visually distinct under /tmp/regen-cr
        rundir = new_room(f"{kind + '-' if kind else ''}{stem}")
        manifest[os.path.abspath(f)] = rundir
        cmd = [sys.executable, os.path.join(SKILL, "regen_phase1.py"), os.path.abspath(f), rundir]
        if lib:
            cmd += ["--lib", os.path.abspath(lib)]
        if kind:
            cmd += ["--kind", kind]
        jobs.append(cmd)
    _run_jobs(jobs, concurrency)
    os.makedirs(BASE, exist_ok=True)
    json.dump(manifest, open(os.path.join(BASE, "batch_manifest.json"), "w"), indent=2)
    print(f"=== BATCH PHASE1 DONE: {len(files)} file(s); manifest at {BASE}/batch_manifest.json ===")
    for f, rd in manifest.items():
        print(f"  {os.path.basename(f)} -> {rd}")
    print("  Next (in-session): run the picker per room, then `regen_batch.py phase2 <conc> <voice> <rooms>`.")


def phase2(argv):
    tight = "--tight" in argv
    argv = [a for a in argv if a != "--tight"]
    concurrency = int(argv[0])
    voice = argv[1]
    rundirs = argv[2:]
    extra = ["--tight"] if tight else []
    jobs = [[sys.executable, os.path.join(SKILL, "regen_phase2.py"), os.path.abspath(rd), voice] + extra for rd in rundirs]
    _run_jobs(jobs, concurrency)
    print(f"=== BATCH PHASE2 DONE: {len(rundirs)} room(s) ===")


def main():
    require_claude()
    if len(sys.argv) < 2 or sys.argv[1] not in ("phase1", "phase2"):
        sys.exit("usage: regen_batch.py phase1 <conc> [--lib <facts>] <file...>  |  "
                 "phase2 <conc> <voice> [--tight] <rundir...>")
    {"phase1": phase1, "phase2": phase2}[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
