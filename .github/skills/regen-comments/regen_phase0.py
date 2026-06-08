#!/usr/bin/env python3
"""regen-comments — PHASE 0 (library grounding; library-aware mode only).

Builds the cross-file LIBRARY_FACTS.md ledger for a whole library/dir so every per-file run can ride it in
as read-only context. Collects the library's `.py` source (skipping tests + `__pycache__`), strips each
(clean-room: library facts come from code BEHAVIOR, not comments), lays them under `<libroom>/lib/`
preserving subpackage layout, then runs the broad library-triage prompt (`library_triage.md`) as ONE
clean-room `claude -p` from the libroom. Output: `<libroom>/LIBRARY_FACTS.md` — domain + cross-file
contracts + glossary, the same telegraphic ledger shape as the per-file ledger, just at library scope.

The orchestrator runs this ONCE when the target is a directory, then passes the result into each per-file
phase 1 via `--lib`, so the per-file lenses, writers, and selector all consult it (the per-file
code stays the source of truth for that file).

Usage: regen_phase0.py <library_dir> <libroom>
"""
import os
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from strip import strip_code  # noqa: E402
from preflight import require_claude  # noqa: E402

# Library FACTS come from the source contracts, not tests/build artifacts; keep those out of the triage.
SKIP_DIRS = {"__pycache__", "tests", "functional_tests", ".git", ".scratch", ".idea", "build", "dist"}


def _is_test_file(name):
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def collect(libdir):
    """Every non-test `.py` under libdir, sorted, skipping build/test/cache dirs."""
    out = []
    for root, dirs, files in os.walk(libdir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py") and not _is_test_file(f):
                out.append(os.path.join(root, f))
    return sorted(out)


def library_prompt():
    """The prompt body of library_triage.md (everything after the `## Prompt` heading)."""
    md = open(os.path.join(SKILL, "library_triage.md")).read()
    return md.split("## Prompt", 1)[1].strip()


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: regen_phase0.py <library_dir> <libroom>")
    require_claude()
    libdir = os.path.abspath(sys.argv[1])
    libroom = os.path.abspath(sys.argv[2])
    os.makedirs(os.path.join(libroom, "lib"), exist_ok=True)

    files = collect(libdir)
    if not files:
        sys.exit(f"no library .py files under {libdir}")
    for fp in files:
        rel = os.path.relpath(fp, libdir)
        dest = os.path.join(libroom, "lib", rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            open(dest, "w").write(strip_code(open(fp).read()))
        except SyntaxError:
            shutil.copy(fp, dest)  # unparseable file: copy raw so triage still sees its contracts

    print(f"library triage over {len(files)} file(s):")
    for fp in files:
        print("  ", os.path.relpath(fp, libdir))

    # one clean-room claude -p: reads ./lib/, writes ./LIBRARY_FACTS.md (cwd outside the project = no CLAUDE.md)
    subprocess.run(
        ["claude", "-p", library_prompt(),
         "--allowedTools", "Read", "Grep", "Glob", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=libroom, capture_output=True, text=True,
    )
    lf = os.path.join(libroom, "LIBRARY_FACTS.md")
    if not os.path.exists(lf):
        sys.exit("library triage produced no LIBRARY_FACTS.md — check the libroom.")

    print("=== PHASE 0 COMPLETE ===")
    print(f"  LIBRARY_FACTS.md: {lf}")
    print(f"  Bytes: {os.path.getsize(lf)}")
    print("  Next (in-session): for each file, run regen_phase1.py --lib <this> -> picker -> regen_phase2.py.")


if __name__ == "__main__":
    main()
