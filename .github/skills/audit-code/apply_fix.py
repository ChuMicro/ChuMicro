#!/usr/bin/env python3
"""audit-code — apply-side helper: extract the selected findings, and run the gate tests.

Applying a fix CHANGES code, so unlike a comment rewrite there is no byte-identity safety net. The apply is
deliberately in-session and human-watched: the orchestrator reads the selected findings (`plan`), makes the
edits with the normal Edit tool so the human sees each one, then gates with `runtests` and a `git diff`
before leaving the change in the working tree, uncommitted. This script does the two mechanical jobs that
benefit from being a script: pulling the chosen findings out of eval.json by number, and locating + running
the host test runner (re-locating each time, so a newly added test file is picked up).

Usage:
  apply_fix.py plan <rundir> <id[,id...]>       # print the selected findings as an edit spec (text + JSON)
  apply_fix.py runtests <target.py> [--tests <p[,p...]>]   # run pytest on the file's tests; exit = pytest's
"""
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from audit_phase1 import find_tests, _find_lib_root  # noqa: E402


def _parse_ids(arg):
    out = []
    for tok in arg.replace(" ", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(int(tok))
    return out


def _load(rundir, name, default):
    fp = os.path.join(rundir, name)
    return json.load(open(fp)) if os.path.exists(fp) else default


def cmd_plan(rundir, ids_arg):
    ids = set(_parse_ids(ids_arg))
    ev = _load(rundir, "eval.json", {"findings": []})
    ev = ev.get("findings", []) if isinstance(ev, dict) else ev
    patch_map = {p.get("id"): p for p in _load(rundir, "patches.json", {"patches": []}).get("patches", [])}
    written_map = {w.get("id"): w for w in _load(rundir, "written.json", {"findings": []}).get("findings", [])}
    chosen = sorted([f for f in ev if f.get("id") in ids], key=lambda x: x.get("id", 0))
    missing = ids - {f.get("id") for f in chosen}
    print(f"=== APPLY PLAN: {len(chosen)} finding(s) selected ===")
    if missing:
        print(f"  WARNING: no finding for id(s): {sorted(missing)}")
    # attach the ready-made patch so the orchestrator can apply via Edit(old=before, new=after)
    spec = []
    for f in chosen:
        fid = f.get("id")
        p = patch_map.get(fid, {})
        w = written_map.get(fid, {})
        title = w.get("title") or f.get("defect", "")
        consequence = w.get("consequence") or f.get("bite", "")
        print(f"\n--- #{fid}  [{f.get('angle')}/{f.get('severity')}/effort:{f.get('effort')}]  {title}")
        print(f"    symbol: {f.get('symbol')}    site: {f.get('site')}")
        print(f"    consequence: {consequence}")
        print(f"    fix: {w.get('suggested_fix') or f.get('fix')}")
        print(f"    patch kind: {p.get('kind', '(none)')}")
        if p.get("kind") == "replace":
            print("    apply: Edit(old_string=<before>, new_string=<after>) on the target")
        elif p.get("kind") == "add":
            print(f"    apply: insert <after> ({p.get('location_hint', 'see note')})")
        elif p.get("kind") == "manual":
            print(f"    apply: manual — {p.get('note')}")
        spec.append({**f, **w, "patch": p})
    # structured form (incl. the patch before/after) for the orchestrator to act on precisely
    print("\n=== PLAN JSON ===")
    print(json.dumps(spec, indent=2))
    return 0


def cmd_runtests(target, override=None):
    paths = [p.strip() for p in override.split(",")] if override else find_tests(target)
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        print(f"=== RUNTESTS: no test files found for {os.path.basename(target)} ===")
        print("  (a coverage fix may need you to ADD a test first; re-run after writing it.)")
        return 0
    root = _find_lib_root(target)
    print(f"=== RUNTESTS: {len(paths)} file(s), cwd={root} ===")
    for p in paths:
        print(f"  - {p}")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *paths], cwd=root,
                       capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.splitlines()[-25:])
    print(tail)
    print(f"=== pytest exit {r.returncode} ({'PASS' if r.returncode == 0 else 'FAIL'}) ===")
    return r.returncode


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "plan":
        sys.exit(cmd_plan(os.path.abspath(sys.argv[2]), sys.argv[3]))
    if len(sys.argv) >= 3 and sys.argv[1] == "runtests":
        override = sys.argv[sys.argv.index("--tests") + 1] if "--tests" in sys.argv else None
        sys.exit(cmd_runtests(sys.argv[2], override))
    sys.exit("usage: apply_fix.py plan <rundir> <ids> | runtests <target.py> [--tests <paths>]")


if __name__ == "__main__":
    main()
