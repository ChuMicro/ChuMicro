#!/usr/bin/env python3
"""Deterministic tic/leak auto-route: swap a flagged symbol for a clean alternative pass's take (no LLM).

The selector picks one whole writer pass, so a single tic-ridden docstring ships even when another cached
pass has a clean take on that symbol. This step runs right after the winner copy in phase 2: it scans the
merged file with flag_tics' detector, and for each flagged symbol tries the OTHER cached passes in number
order, splicing in the first take that (a) keeps the executable code AST-identical and (b) scans clean for
that symbol. Class symbols take the class docstring only (methods have their own rows). Substitutions are
recorded as `autoroute` in pick.json and surfaced in the report — the human still gates everything, and
every spliced text is verbatim from a complete pass (the no-rewrite guarantee holds). Flags with no clean
alternative are left for the human; this never rewrites.

Runs BEFORE polish on purpose, so a routed-in raw pass still gets the mechanical-ban fix loop.

Usage: autoroute_tics.py <rundir> <voice> [<file>]   (default file: <rundir>/merged.py)
"""
import ast
import glob
import json
import os
import re
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from flag_tics import scan, signatures  # noqa: E402
from splice_symbol import splice, _code_only, _find  # noqa: E402
from apply_selection import set_docstring, _is_class  # noqa: E402


def main():
    rundir = os.path.abspath(sys.argv[1])
    voice = sys.argv[2]
    target = sys.argv[3] if len(sys.argv) > 3 else os.path.join(rundir, "merged.py")
    if not os.path.exists(target):
        print("autoroute: no merged file; skipping")
        return
    pick_path = os.path.join(rundir, "pick.json")
    pick = json.load(open(pick_path)) if os.path.exists(pick_path) else {}
    winner = pick.get("winner")

    src = open(target).read()
    spath = os.path.join(rundir, "stripped.py")
    code = open(spath).read().lower() if os.path.exists(spath) else ""
    descriptor = json.load(open(os.path.join(SKILL, "voices.json")))["voices"].get(voice, "")
    sigs = signatures(descriptor) if descriptor else set()

    flags = scan(src, sigs, code)
    flagged = []
    for f in flags:
        if f["symbol"] not in flagged:
            flagged.append(f["symbol"])
    if not flagged:
        print("autoroute: no tic/leak flags; nothing to route")
        return

    candidates = []
    for rf in sorted(glob.glob(os.path.join(rundir, "runs", "run-*.py"))):
        n = int(re.search(r"run-(\d+)\.py$", rf).group(1))
        if n != winner:
            candidates.append((n, open(rf).read()))

    fingerprint = _code_only(src)
    routed = []
    for sym in flagged:
        for n, run_src in candidates:
            try:
                if sym != "<module>" and _is_class(src, sym):
                    new_doc = ast.get_docstring(_find(ast.parse(run_src), sym))
                    if new_doc is None:
                        continue
                    trial = set_docstring(src, sym, new_doc)
                else:
                    trial = splice(src, run_src, sym)
            except (SystemExit, SyntaxError):
                continue  # pass lacks the symbol / un-spliceable — try the next one
            if _code_only(trial) != fingerprint:
                continue
            if any(f["symbol"] == sym for f in scan(trial, sigs, code)):
                continue  # this pass's take is flagged too
            src = trial
            routed.append({"symbol": sym, "to_run": n})
            break

    if routed:
        open(target, "w").write(src)
        pick["autoroute"] = routed
        json.dump(pick, open(pick_path, "w"), indent=2)
        for r in routed:
            print(f"autoroute: {r['symbol']} -> writer pass {r['to_run']} (flagged in pass {winner})")
    leftover = [s for s in flagged if not any(r["symbol"] == s for r in routed)]
    if leftover:
        print(f"autoroute: no clean alternative for {', '.join(leftover)} — left flagged for the human")


if __name__ == "__main__":
    main()
