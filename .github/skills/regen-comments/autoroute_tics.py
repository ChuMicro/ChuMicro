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
VOICES_DIR = os.path.normpath(os.path.join(SKILL, os.pardir, "_shared", "voices"))
sys.path.insert(0, SKILL)
from apply_selection import _is_class, set_docstring  # noqa: E402
from flag_tics import scan, signatures, symbol_spans  # noqa: E402
from splice_symbol import _code_only, _find, splice  # noqa: E402
from tics import detect  # noqa: E402


def ban_symbols(src):
    """Qualnames whose docstrings/comments carry a mechanical-ban violation (tics.py detect).

    detect() names docstring sites by SHORT name and comments by line number; both map onto the
    symbol spans flag_tics already computes. Mechanical bans route exactly like tics/leaks: swap the
    symbol for an alternative pass's clean take instead of paying an LLM polish round for it.
    """
    tree = ast.parse(src)
    spans = symbol_spans(tree)

    def qual_for_line(line):
        best = ("<module>", -1)
        for q, s, e in spans:
            if s <= line <= e and s > best[1]:
                best = (q, s)
        return best[0]

    out = set()
    for v in detect(src):
        where = v.get("where", "")
        if where.startswith("docstring:"):
            short = where.split(":", 1)[1]
            if short == "<module>":
                out.add("<module>")
            else:
                # short name -> qualname(s); a name shared across classes flags each owner
                out.update(q for q, _s, _e in spans if q.split(".")[-1] == short)
        elif where.startswith("comment:L"):
            out.add(qual_for_line(int(where.split("L", 1)[1])))
    return out


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
    descriptor = json.load(open(os.path.join(VOICES_DIR, "voices.json")))["voices"].get(voice, "")
    sigs = signatures(descriptor) if descriptor else set()

    flags = scan(src, sigs, code)
    flagged = []
    for f in flags:
        if f["symbol"] not in flagged:
            flagged.append(f["symbol"])
    for sym in sorted(ban_symbols(src)):   # mechanical bans (em-dash / semicolon / banned words) route too
        if sym not in flagged:
            flagged.append(sym)
    if not flagged:
        print("autoroute: no tic/leak/ban flags; nothing to route")
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
            if any(f["symbol"] == sym for f in scan(trial, sigs, code)) or sym in ban_symbols(trial):
                continue  # this pass's take is flagged (tic/leak) or ban-dirty too
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
