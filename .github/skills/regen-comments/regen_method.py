#!/usr/bin/env python3
"""Method scope: regenerate ONE symbol's docstring + comments and splice it onto the ORIGINAL file.

For a method-scoped run the user flagged a single symbol, so the deliverable is the original file with only
THAT symbol re-commented and everything else left exactly as it was. Phase 1 + phase 2 run on the whole file
(the writer needs the surrounding code + the ledger for context) and leave `merged.py` -- a full regenerated
candidate whose executable code is byte-identical to the original. This splices only the target symbol's span
from `merged.py` onto a copy of the original (so every other symbol keeps its existing comments), then
verifies the executable code is unchanged.

Usage: regen_method.py <original_file.py> <rundir> <voice> <qualname>
  qualname: "<module>", "func", "Class", or "Class.method".
Precondition: phase 2 ran in <rundir> for <original_file.py> (merged.py exists).
"""
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))


def main():
    original, rundir, voice, qual = sys.argv[1], os.path.abspath(sys.argv[2]), sys.argv[3], sys.argv[4]
    merged = os.path.join(rundir, "merged.py")
    if not os.path.exists(merged):
        sys.exit(f"no merged.py in {rundir} — run phase 2 on the whole file before the method splice.")
    out = os.path.join(rundir, f"METHOD_{voice}.py")
    # splice only the target symbol from the regenerated candidate onto the original (code-identity guarded)
    r = subprocess.run([sys.executable, os.path.join(SKILL, "splice_symbol.py"), original, merged, qual, out])
    if r.returncode != 0:
        sys.exit(r.returncode)
    # invariant 4: the executable code must still be byte-identical to the original
    subprocess.run([sys.executable, os.path.join(SKILL, "verify_code.py"), original, out], check=True)
    print("=== METHOD SCOPE COMPLETE ===")
    print(f"  only {qual!r} re-commented; every other symbol kept its existing comments -> {out}")
    print("  Present just that symbol's before/after; apply by copying onto the working tree on confirm.")


if __name__ == "__main__":
    main()
