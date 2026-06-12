#!/usr/bin/env python3
"""audit-code — library context pass (folder / library scope only).

Before evaluating each file in a library, build one cross-file ledger so a per-file lens can interpret a
shared type or contract instead of mis-flagging it. Strips every .py in the library (clean-room: the context
is read from behavior, not comments), lays them under <rundir>/lib/, and runs ONE `claude -p` that writes
LIBRARY_FACTS.md (domain + cross-file contracts + glossary). The orchestrator then passes
`--lib <rundir>/LIBRARY_FACTS.md` to each file's audit_phase1.py run. A single-file evaluation skips this.

Usage: audit_phase0.py <lib_dir> <rundir>   # writes <rundir>/LIBRARY_FACTS.md
"""
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from strip import strip_code  # noqa: E402
from preflight import require_claude  # noqa: E402

PROMPT = (
    "Read the comment-stripped library source under ./lib/ (the files are listed in ./lib_manifest.txt; read "
    "each one). Produce LIBRARY_FACTS.md, a tight cross-file ledger that a per-file reviewer needs to judge "
    "one file without re-deriving the whole library:\n"
    "- DOMAIN: one short paragraph on what this library does in the real world.\n"
    "- CONTRACTS: the cross-file contracts -- what each module/class provides and expects, shared types and "
    "their meaning, invariants or protocols that span files (e.g. 'X returns a handle that Y must close').\n"
    "- GLOSSARY: the domain terms a reader must know, defined briefly.\n"
    "Keep it factual and derived from the code; do not invent. Write it to ./LIBRARY_FACTS.md, then reply DONE."
)


def main():
    require_claude()
    if len(sys.argv) < 3:
        sys.exit("usage: audit_phase0.py <lib_dir> <rundir>")
    lib_dir, rundir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    libout = os.path.join(rundir, "lib")
    os.makedirs(libout, exist_ok=True)
    manifest = []
    for dirpath, _dirs, files in os.walk(lib_dir):
        if any(skip in dirpath for skip in ("/tests", "/functional_tests", "/examples", "__pycache__")):
            continue
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            src = open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace").read()
            rel = os.path.relpath(os.path.join(dirpath, fn), lib_dir)
            dst = os.path.join(libout, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                open(dst, "w").write(strip_code(src))
            except SyntaxError:
                open(dst, "w").write(src)
            manifest.append("lib/" + rel)
    open(os.path.join(rundir, "lib_manifest.txt"), "w").write("\n".join(manifest) + "\n")

    # --safe-mode: user-global memory, hooks, skills, plugins, and MCP stay out of the clean room
    subprocess.run(["claude", "--safe-mode", "-p", PROMPT, "--allowedTools", "Read", "Write",
                    "--permission-mode", "acceptEdits", "--model", "opus"],
                   cwd=rundir, capture_output=True, text=True)
    out = os.path.join(rundir, "LIBRARY_FACTS.md")
    if os.path.exists(out):
        print(f"wrote {out}  ({len(manifest)} files)")
    else:
        print(f"WARNING: LIBRARY_FACTS.md not produced (continuing without cross-file context); {len(manifest)} files staged")


if __name__ == "__main__":
    main()
