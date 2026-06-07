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
  regen_batch.py phase1 <concurrency> [--lib <LIBRARY_FACTS.md>] <file1.py> <file2.py> ...
  regen_batch.py phase2 <concurrency> <voice> <rundir1> <rundir2> ...

phase1 writes /tmp/regen-cr/batch_manifest.json mapping each file to its run room (the orchestrator reads it
to drive the pickers + phase 2).
"""
import concurrent.futures as cf
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402

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
    lib = None
    if rest and rest[0] == "--lib":
        lib, rest = rest[1], rest[2:]
    files = rest
    jobs, manifest = [], {}
    for i, f in enumerate(files):
        stem = os.path.splitext(os.path.basename(f))[0]
        rundir = os.path.join(BASE, f"{stem}-{i}")
        manifest[os.path.abspath(f)] = rundir
        cmd = [sys.executable, os.path.join(SKILL, "regen_phase1.py"), os.path.abspath(f), rundir]
        if lib:
            cmd += ["--lib", os.path.abspath(lib)]
        jobs.append(cmd)
    _run_jobs(jobs, concurrency)
    os.makedirs(BASE, exist_ok=True)
    json.dump(manifest, open(os.path.join(BASE, "batch_manifest.json"), "w"), indent=2)
    print(f"=== BATCH PHASE1 DONE: {len(files)} file(s); manifest at {BASE}/batch_manifest.json ===")
    for f, rd in manifest.items():
        print(f"  {os.path.basename(f)} -> {rd}")
    print("  Next (in-session): run the picker per room, then `regen_batch.py phase2 <conc> <voice> <rooms>`.")


def phase2(argv):
    concurrency = int(argv[0])
    voice = argv[1]
    rundirs = argv[2:]
    jobs = [[sys.executable, os.path.join(SKILL, "regen_phase2.py"), os.path.abspath(rd), voice] for rd in rundirs]
    _run_jobs(jobs, concurrency)
    print(f"=== BATCH PHASE2 DONE: {len(rundirs)} room(s) ===")


def main():
    require_claude()
    if len(sys.argv) < 2 or sys.argv[1] not in ("phase1", "phase2"):
        sys.exit("usage: regen_batch.py phase1 <conc> [--lib <facts>] <file...>  |  "
                 "phase2 <conc> <voice> <rundir...>")
    {"phase1": phase1, "phase2": phase2}[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
