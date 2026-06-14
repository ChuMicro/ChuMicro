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
  apply_fix.py parse-selection <blob-file> [--merged <merged.json>]   # normalize a picker blob or typed
        # selection into a JSON choice vector: choices, per-id notes, bare-number lists as apply-these,
        # and (with --merged, i.e. library scope) bare numeric ids flagged ambiguous for the orchestrator
        # to resolve. Defaults-unchanged detection stays with the orchestrator, which holds spec.json.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from audit_phase1 import _find_lib_root, find_tests  # noqa: E402

GATE_FILE = os.path.join(SKILL, os.pardir, "_shared", "apply_gate.py")


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


def repo_gate(target):
    """Run the repo-specific apply gate when one is defined; return its exit code (0 = pass).

    ../_shared/apply_gate.py is the porting seam: its gate_command(path) maps the edited file to
    an extra gate command plus a reason (this repo: the package's cross-runtime suite for
    libraries/ and support/ files), or None when the universal pytest gate suffices. No seam
    file at all — a repo these skills were ported to without one — means no extra gate."""
    if not os.path.exists(GATE_FILE):
        return 0
    spec = importlib.util.spec_from_file_location("apply_gate", GATE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           cwd=os.path.dirname(os.path.abspath(target)) or ".",
                           capture_output=True, text=True)
    repo_root = probe.stdout.strip()
    rel = os.path.relpath(os.path.abspath(target), repo_root) if repo_root else target
    gate = module.gate_command(rel)
    if not gate:
        return 0
    argv, reason = gate
    print(f"=== REPO GATE: {' '.join(argv)} ===")
    print(f"  ({reason})")
    r = subprocess.run(argv, cwd=repo_root or None, capture_output=True, text=True)
    tail = "\n".join(((r.stdout or "") + (r.stderr or "")).splitlines()[-15:])
    print(tail)
    print(f"=== repo gate exit {r.returncode} ({'PASS' if r.returncode == 0 else 'FAIL'}) ===")
    return r.returncode


def cmd_runtests(target, override=None):
    paths = [p.strip() for p in override.split(",")] if override else find_tests(target)
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        print(f"=== RUNTESTS: no test files found for {os.path.basename(target)} ===")
        print("  (a coverage fix may need you to ADD a test first; re-run after writing it.)")
        return repo_gate(target)
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
    if r.returncode != 0:
        return r.returncode
    return repo_gate(target)


_CHOICE_LINE = re.compile(r"^\s*([A-Za-z0-9_.-]+#\d+|\d+)\s*=\s*(apply|discuss|skip)\s*$")
_NOTE_LINE = re.compile(r"^\s*note\s+([A-Za-z0-9_.-]+#\d+|\d+)\s*:\s*(.*\S)\s*$")
_ID_TOKEN = re.compile(r"^(?:[A-Za-z0-9_.-]+#\d+|\d+)$")


def cmd_parse_selection(blob_path, merged_path=None):
    """Normalize a picker blob or typed selection into one JSON choice vector on stdout.

    Accepts three input forms, mixed freely: `<id> = <choice>` lines, `note <id>: <text>` riders
    (appended when an id carries several), and lines of bare id tokens (`3, 7, 12`) read as
    apply-these. With --merged (library scope, where ids are namespaced like `heartbeat#3`), a
    bare numeric id is flagged in `ambiguous` instead of guessed at. Unrecognized non-empty lines
    land in `unparsed` so nothing is silently dropped."""
    text = sys.stdin.read() if blob_path == "-" else open(blob_path).read()
    library_scope = bool(merged_path) and os.path.exists(merged_path)
    choices, notes, ambiguous, unparsed = {}, {}, [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("PICKS"):
            continue
        m = _CHOICE_LINE.match(line)
        if m:
            choices[m.group(1)] = m.group(2)
            continue
        m = _NOTE_LINE.match(line)
        if m:
            key = m.group(1)
            notes[key] = (notes[key] + " " + m.group(2)) if key in notes else m.group(2)
            continue
        tokens = [t for t in re.split(r"[,\s]+", line) if t]
        if tokens and all(_ID_TOKEN.match(t) for t in tokens):
            for t in tokens:
                choices.setdefault(t, "apply")
            continue
        unparsed.append(line)
    if library_scope:
        ambiguous = sorted([i for i in choices if i.isdigit()], key=int)
    result = {
        "choices": choices,
        "notes": notes,
        "apply": [i for i, c in choices.items() if c == "apply"],
        "discuss": [i for i, c in choices.items() if c == "discuss"],
        "skip": [i for i, c in choices.items() if c == "skip"],
        "ambiguous": ambiguous,
        "unparsed": unparsed,
    }
    print(json.dumps(result, indent=2))
    return 0


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "parse-selection":
        merged = sys.argv[sys.argv.index("--merged") + 1] if "--merged" in sys.argv else None
        sys.exit(cmd_parse_selection(sys.argv[2], merged))
    if len(sys.argv) >= 4 and sys.argv[1] == "plan":
        sys.exit(cmd_plan(os.path.abspath(sys.argv[2]), sys.argv[3]))
    if len(sys.argv) >= 3 and sys.argv[1] == "runtests":
        override = sys.argv[sys.argv.index("--tests") + 1] if "--tests" in sys.argv else None
        sys.exit(cmd_runtests(sys.argv[2], override))
    sys.exit("usage: apply_fix.py plan <rundir> <ids> | runtests <target.py> [--tests <paths>] | "
             "parse-selection <blob-file> [--merged <merged.json>]")


if __name__ == "__main__":
    main()
