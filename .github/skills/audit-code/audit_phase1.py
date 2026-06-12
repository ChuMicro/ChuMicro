#!/usr/bin/env python3
"""audit-code — EVALUATION phase. Mechanical + clean-room, no human gate.

Strips the target so the code lenses read behavior with no comment to anchor them, copies the ORIGINAL
(commented) file for the drift lens, locates and concatenates the file's tests for the coverage lens, then
runs the evaluation workflow as ONE `claude -p` from a /tmp room (clean: no project CLAUDE.md by
cwd-ancestry, file access bounded to the room). The workflow runs a summarizer + four lenses, a merger that
assigns stable fix numbers, and a fixture-agnostic validator re-check loop. It then collects what the
in-session orchestrator renders:
  - eval.json        (numbered findings + domain facts, validator-converged)
  - summary.json     (independent module + per-symbol summaries)
  - validation.json  (per-finding real / fix_sound verdicts; convergence)
  - phase1.json      (counts + convergence + the located test files, for the orchestrator)

The HTML render, the human's fix-number selection, and the guarded apply all happen IN-SESSION, after this
phase -- a headless subprocess cannot ask the user anything.

Usage: audit_phase1.py <target.py> <rundir> [--voice <key>] [--tests <path[,path...]>] [--lib <FACTS.md>]
"""
import json
import os
import re
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402

TEST_DIRS = ("tests", "functional_tests")


def voice_persona(key):
    """The persona string for a voice key from the shared registry (empty for plain / unknown / None)."""
    if not key or key == "plain":
        return ""
    try:
        from voices import REG
        return json.load(open(REG)).get("voices", {}).get(key, "")
    except OSError:
        return ""


def _find_lib_root(target):
    """Nearest ancestor of the target that looks like a library root (has a tests/ dir or a pyproject)."""
    d = os.path.dirname(os.path.abspath(target))
    while True:
        if any(os.path.isdir(os.path.join(d, t)) for t in TEST_DIRS) or \
           os.path.exists(os.path.join(d, "pyproject.toml")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.dirname(os.path.abspath(target))
        d = parent


def find_tests(target):
    """Locate the test files that exercise `target`.

    Looks under the library root's tests/ and functional_tests/ for any .py whose NAME contains the target's
    stem, or whose TEXT references the stem as a word (an `import foo` / `from x import foo` / `foo.` use).
    Returns a de-duplicated, sorted list of absolute paths -- possibly empty (then the coverage lens is told
    no tests exist). Name-stem and text matches are both included so a test file named for the class rather
    than the module is still found.
    """
    stem = os.path.splitext(os.path.basename(target))[0]
    root = _find_lib_root(target)
    word = re.compile(r"\b" + re.escape(stem) + r"\b")
    found = set()
    for td in TEST_DIRS:
        d = os.path.join(root, td)
        if not os.path.isdir(d):
            continue
        for dirpath, _dirs, files in os.walk(d):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dirpath, fn)
                if stem in fn:
                    found.add(p)
                    continue
                try:
                    if word.search(open(p, encoding="utf-8", errors="replace").read()):
                        found.add(p)
                except OSError:
                    pass
    return sorted(found)


def build_tests_file(target, out_path, override=None):
    """Concatenate the located (or user-overridden) tests into one file for the coverage lens.

    Each file is fenced with a `# ===== <path> =====` banner so the lens can attribute a gap to its file.
    Writes a NO-TESTS marker when none are found, which the coverage lens treats as "the whole surface is
    unverified" rather than emitting one finding per method.
    """
    paths = [p.strip() for p in override.split(",")] if override else find_tests(target)
    paths = [p for p in paths if p and os.path.exists(p)]
    with open(out_path, "w", encoding="utf-8") as out:
        if not paths:
            out.write(f"# NO-TESTS MARKER: no test files were found for {os.path.basename(target)}.\n"
                      f"# Treat the module's important behaviors as UNVERIFIED.\n")
        else:
            for p in paths:
                out.write(f"\n# ===== {p} =====\n")
                out.write(open(p, encoding="utf-8", errors="replace").read())
                out.write("\n")
    return paths


def claude_p_workflow(rundir, wf_name):
    """Run one clean-room `claude -p` from rundir that executes the named workflow to completion.

    --safe-mode keeps user-global ~/.claude/CLAUDE.md, hooks, skills, plugins, and MCP servers out
    of every judging layer (OAuth login and the Workflow/Task tools still work under it), so the
    clean room guarantees what its name claims instead of warning about the leak."""
    return subprocess.run(
        ["claude", "--safe-mode", "-p",
         f"Use the Workflow tool to run the workflow at ./{wf_name} (call Workflow with scriptPath "
         f"./{wf_name}). Wait for full completion, then reply DONE.",
         "--allowedTools", "Workflow", "Task", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=rundir, capture_output=True, text=True,
    )


def _stage(wf_src, rundir, **subs):
    src = open(os.path.join(SKILL, wf_src)).read()
    for k, v in subs.items():
        src = src.replace(k, v)
    open(os.path.join(rundir, wf_src), "w").write(src)


def main():
    require_claude()
    args = sys.argv[1:]
    lib = args[args.index("--lib") + 1] if "--lib" in args else None
    tests_override = args[args.index("--tests") + 1] if "--tests" in args else None
    voice = args[args.index("--voice") + 1] if "--voice" in args else None
    flag_vals = {v for v in (lib, tests_override, voice) if v is not None}
    pos = [a for a in args if not a.startswith("--") and a not in flag_vals]
    if len(pos) < 2:
        sys.exit("usage: audit_phase1.py <target.py> <rundir> [--voice <key>] [--tests <paths>] [--lib <FACTS.md>]")
    target, rundir = pos[0], os.path.abspath(pos[1])

    # Freshness guard: a room already holding a prior eval means two runs collided or a stale dir is being
    # reused -- both poison the result. Allocate a fresh room with rooms.py instead.
    if os.path.isdir(rundir):
        existing = os.listdir(rundir)
        if "phase1.json" in existing or "eval.json" in existing:
            sys.exit(f"run room {rundir} already holds a prior eval; allocate a FRESH room "
                     f"(RUN=$(python3 {SKILL}/rooms.py new <slug>)) so parallel or stale runs can't collide.")
    os.makedirs(os.path.join(rundir, "findings"), exist_ok=True)

    # mechanical inputs: stripped (code truth for the lenses), commented (the drift lens), tests (coverage)
    subprocess.run([sys.executable, os.path.join(SKILL, "strip.py"), target,
                    os.path.join(rundir, "stripped.py")], check=True)
    shutil.copy(target, os.path.join(rundir, "commented.py"))
    tests_found = build_tests_file(target, os.path.join(rundir, "tests.py"), tests_override)
    if lib:
        shutil.copy(lib, os.path.join(rundir, "LIBRARY_FACTS.md"))
    # voice: write the persona to a file (so its quotes/newlines never break the workflow JS). The writer
    # reads it -- empty persona (plain / none) -> the writer composes in a plain register; otherwise it
    # composes FULLY in that voice. Voice is written at compose time, never as a post-hoc rewrite.
    open(os.path.join(rundir, "voice_persona.txt"), "w").write(voice_persona(voice))

    # the evaluation workflow, one clean-room claude -p
    _stage("audit_wf.js", rundir, __RUNDIR__=rundir)
    claude_p_workflow(rundir, "audit_wf.js")

    # collect
    def _load(p, default):
        fp = os.path.join(rundir, p)
        return json.load(open(fp)) if os.path.exists(fp) else default

    ev = _load("eval.json", {"findings": [], "domain_facts": []})
    if isinstance(ev, list):                       # tolerate a bare-array slip
        ev = {"findings": ev, "domain_facts": []}
    val = _load("validation.json", {})
    summary = _load("summary.json", {"module_summary": "", "symbols": []})
    patches = _load("patches.json", {"patches": []})
    written = _load("written.json", {"findings": []})
    findings = ev.get("findings", [])
    converged = not (val.get("any_unreal") or val.get("any_fix_unsound"))

    def _count(key):
        out = {}
        for f in findings:
            out[f.get(key)] = out.get(f.get(key), 0) + 1
        return out

    npatch = len(patches.get("patches", []))
    phase1 = {
        "target": os.path.abspath(target),
        "rundir": rundir,
        "voice": voice or "plain",
        "converged": converged,
        "n_findings": len(findings),
        "n_written": len(written.get("findings", [])),
        "n_patches": npatch,
        "by_angle": _count("angle"),
        "by_severity": _count("severity"),
        "tests_found": tests_found,
        "n_symbols": len(summary.get("symbols", [])),
        "eval_json": os.path.join(rundir, "eval.json"),
        "written_json": os.path.join(rundir, "written.json"),
        "summary_json": os.path.join(rundir, "summary.json"),
        "validation_json": os.path.join(rundir, "validation.json"),
        "patches_json": os.path.join(rundir, "patches.json"),
    }
    json.dump(phase1, open(os.path.join(rundir, "phase1.json"), "w"), indent=2)

    print("=== AUDIT PHASE COMPLETE ===")
    print(f"  rundir: {rundir}")
    print(f"  target: {target}   voice: {voice or 'plain'}")
    print(f"  tests found: {len(tests_found)}" + ("" if tests_found else "  (none -> coverage lens treats surface as unverified)"))
    for p in tests_found:
        print(f"      - {p}")
    print(f"  symbols summarized: {phase1['n_symbols']}")
    print(f"  findings: {len(findings)}   by angle: {phase1['by_angle']}   by severity: {phase1['by_severity']}")
    print(f"  prose written: {phase1['n_written']}   patches generated: {npatch}")
    print(f"  validator: {'converged clean' if converged else 'left some findings unconfirmed (report flags them)'}")
    print("  Next (in-session): render_eval.py to build + open the HTML, then the selection/apply loop.")


if __name__ == "__main__":
    main()
