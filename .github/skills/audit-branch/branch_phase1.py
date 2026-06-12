#!/usr/bin/env python3
"""audit-branch — EVALUATION phase. Mechanical + clean-room, no human gate.

Stages a change-set into a run room so six lenses can judge it without project memory: the unified
diff, head-side copies of every changed file (commented, for the intent/craft lenses and the
patcher), comment-stripped head and base copies (the code lenses' only source of truth), the
traced usage files of every changed symbol (stripped), the changed files' located tests, and the
branch's commit messages as the intent record. Then runs the evaluation workflow as ONE
`claude -p` from the room (clean: no project CLAUDE.md by cwd-ancestry, file access bounded to
the room) and collects what the in-session orchestrator renders:
  - eval.json        (numbered findings + intent facts, validator-converged)
  - written.json     (reader prose in the chosen voice)
  - summary.json     (independent what-this-change-set-does + per-file change summaries)
  - validation.json  (per-finding real / fix_sound verdicts; convergence)
  - patches.json     (apply-ready before/after per finding, each naming its file)
  - phase1.json      (counts + convergence + the staged file list, for the orchestrator)

Nothing here mutates the repo: base/head contents come from `git show` blobs, never a checkout.
Test files are located in the working tree (find_tests), so a range whose head is not the current
checkout still gets the tests that exist on disk now.

Usage:
  branch_phase1.py <base_ref> <head_ref> <rundir> [--repo <root>] [--voice <key>]
                   [--intent <text-or-path>] [--facts <FEATURE_FACTS.md>]
  branch_phase1.py --staged <rundir> [flags]      # index vs HEAD
  branch_phase1.py --worktree <rundir> [flags]    # working tree vs HEAD

`--stage-only` stops after the mechanical staging (no `claude -p`) — for debugging what the
lenses would see, and for the TESTPLAN's fixture rows.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
# the clean-room pipeline helpers live in the sibling audit-code skill (one pipeline home,
# two front doors); this skill stages differently but runs the same room machinery
PIPELINE = os.path.join(os.path.dirname(SKILL), "audit-code")
sys.path.insert(0, PIPELINE)
from audit_phase1 import claude_p_workflow, find_tests, voice_persona, write_repros  # noqa: E402
from preflight import require_claude  # noqa: E402
from strip import strip_code  # noqa: E402

MAX_USAGE_FILES = 40
MAX_USAGE_BYTES = 100_000          # per file; a generated monster would drown the lens
MAX_GREP_NAMES = 30
SKIP_USAGE_DIRS = ("tests/", "functional_tests/", ".scratch/", ".tools/", ".venv/", "__pycache__/")


def _git(repo, *args, check=True):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def changed_files(repo, mode, base, head):
    """List the change-set's files as (status, path) pairs.

    Range mode diffs against the merge base (three-dot semantics) so commits that landed on the
    base after the branch forked do not show up as the branch's changes. A rename (R<score>)
    reports the NEW path with status M plus the old path as a separate D entry, so base/head
    staging stays one-path-per-entry.
    """
    if mode == "staged":
        raw = _git(repo, "diff", "--cached", "--name-status")
    elif mode == "worktree":
        raw = _git(repo, "diff", "HEAD", "--name-status")
    else:
        raw = _git(repo, "diff", f"{base}...{head}", "--name-status")
    out = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) == 3:
            out.append(("D", parts[1]))
            out.append(("M", parts[2]))
        else:
            out.append((status[0], parts[1]))
    return out


def _blob(repo, ref, path):
    """The file's content at one side of the change-set, or None when it does not exist there.

    head side: ref is the head ref (range), ":" (the index, staged mode), or None (read the
    working tree). base side: the merge base (range) or HEAD (staged/worktree)."""
    if ref is None:
        full = os.path.join(repo, path)
        if not os.path.exists(full):
            return None
        return open(full, encoding="utf-8", errors="replace").read()
    spec = f"{ref}:{path}" if ref != ":" else f":{path}"
    result = subprocess.run(["git", "show", spec], cwd=repo, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def _write_stripped(text, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        open(dest, "w").write(strip_code(text))
    except SyntaxError:
        open(dest, "w").write(text)


def diff_new_ranges(diff_text):
    """Per-file new-side changed line ranges from the unified diff: {path: [(start, end), ...]}.

    Hunk headers carry the new-side start and length (@@ -a,b +c,d @@); the ranges are what the
    symbol mapper intersects with each def's span to decide which symbols the change touches."""
    ranges = {}
    current = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("@@") and current:
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match:
                start = int(match.group(1))
                length = int(match.group(2)) if match.group(2) is not None else 1
                ranges.setdefault(current, []).append((start, max(start, start + length - 1)))
    return ranges


def changed_symbols(head_source, line_ranges):
    """Qualnames of the defs/classes whose span intersects a changed line range, plus <module>
    when a change lands outside every def."""
    try:
        tree = ast.parse(head_source)
    except SyntaxError:
        return ["<module>"]
    hits, spans = [], []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                span = (child.lineno, getattr(child, "end_lineno", child.lineno) or child.lineno)
                spans.append(span)
                if any(start <= span[1] and end >= span[0] for start, end in line_ranges):
                    hits.append(qual)
                walk(child, qual + ".")

    walk(tree, "")
    outside = any(not any(span[0] <= start and end <= span[1] for span in spans)
                  for start, end in line_ranges)
    if outside or not hits:
        hits.append("<module>")
    return hits


def top_level_names(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def stage_usages(repo, mode, head, names, changed_paths, rundir):
    """Find and stage (stripped) every repo file that references a changed symbol or module.

    One `git grep -l -w <name>` per traced name, against the head tree (range mode) or the
    working tree. Tests are excluded — they land in tests.py for the coverage lens — and the
    changed files themselves are excluded (the lenses already hold them). Caps keep a hot name
    (a one-word symbol like `tick`) from staging half the repo; usage_map.json records what was
    staged AND what was dropped, so the usage lens knows its horizon."""
    usage_map, staged, dropped = {}, {}, []
    grep_ref = [head] if mode == "range" else []
    for name in sorted(names)[:MAX_GREP_NAMES]:
        result = subprocess.run(
            ["git", "grep", "-l", "-w", name, *grep_ref, "--", "*.py"],
            cwd=repo, capture_output=True, text=True)
        files = []
        for line in result.stdout.splitlines():
            path = line.split(":", 1)[1] if mode == "range" else line
            if path in changed_paths or any(seg in path for seg in SKIP_USAGE_DIRS):
                continue
            files.append(path)
        if files:
            usage_map[name] = files
            for path in files:
                staged.setdefault(path, None)
    for path in sorted(staged):
        if len([p for p in staged.values() if p]) >= MAX_USAGE_FILES:
            dropped.append(path)
            continue
        text = _blob(repo, head if mode == "range" else None, path)
        if text is None or len(text) > MAX_USAGE_BYTES:
            dropped.append(path)
            continue
        _write_stripped(text, os.path.join(rundir, "usages", path))
        staged[path] = True
    json.dump({"traced_names": sorted(names)[:MAX_GREP_NAMES],
               "references": usage_map,
               "staged": sorted(p for p, ok in staged.items() if ok),
               "dropped_over_cap": dropped},
              open(os.path.join(rundir, "usage_map.json"), "w"), indent=1)
    return len([p for p, ok in staged.items() if ok])


def build_intent(repo, mode, base, head, intent_arg):
    """The intent record: every commit message in the range (subject + body), plus any
    user-stated intent (--intent takes a literal string or a file path). Staged/worktree changes
    have no commits yet — the record says so rather than staying silent."""
    parts = []
    if mode == "range":
        log = _git(repo, "log", "--reverse", "--format=== commit %h ==%n%B", f"{base}..{head}")
        parts.append(log.strip() or "(no commits in range)")
    else:
        parts.append(f"(uncommitted {mode} changes — no commit messages exist yet)")
    if intent_arg:
        text = open(intent_arg, encoding="utf-8").read() if os.path.exists(intent_arg) else intent_arg
        parts.append("== stated intent (user-provided) ==\n" + text)
    return "\n\n".join(parts) + "\n"


def main():
    args = sys.argv[1:]
    stage_only = "--stage-only" in args
    if not stage_only:
        require_claude()

    def flag(name):
        return args[args.index(name) + 1] if name in args else None

    repo = os.path.abspath(flag("--repo") or _git(".", "rev-parse", "--show-toplevel").strip())
    voice = flag("--voice")
    intent_arg = flag("--intent")
    facts = flag("--facts")
    mode = "staged" if "--staged" in args else ("worktree" if "--worktree" in args else "range")
    flag_vals = {v for v in (flag("--repo"), voice, intent_arg, facts) if v is not None}
    pos = [a for a in args if not a.startswith("--") and a not in flag_vals]
    if mode == "range":
        if len(pos) < 3:
            sys.exit("usage: branch_phase1.py <base_ref> <head_ref> <rundir> [--repo <root>] "
                     "[--voice <key>] [--intent <text-or-path>] [--facts <FEATURE_FACTS.md>]\n"
                     "       branch_phase1.py --staged|--worktree <rundir> [flags]")
        base, head, rundir = pos[0], pos[1], os.path.abspath(pos[2])
        merge_base = _git(repo, "merge-base", base, head).strip()
    else:
        if len(pos) < 1:
            sys.exit("usage: branch_phase1.py --staged|--worktree <rundir> [flags]")
        base, head, rundir = "HEAD", None, os.path.abspath(pos[0])
        merge_base = _git(repo, "rev-parse", "HEAD").strip()

    # freshness guard: a room already holding a prior eval means two runs collided or a stale
    # dir is being reused — both poison the result; mint rooms with rooms.py
    if os.path.isdir(rundir) and {"phase1.json", "eval.json"} & set(os.listdir(rundir)):
        sys.exit(f"run room {rundir} already holds a prior eval; allocate a FRESH room "
                 f"(RUN=$(python3 {PIPELINE}/rooms.py new <slug>)) so runs can't collide.")
    os.makedirs(os.path.join(rundir, "findings"), exist_ok=True)

    files = changed_files(repo, mode, base, head)
    if not files:
        sys.exit("the change-set is empty — nothing to evaluate "
                 f"({'no staged changes' if mode == 'staged' else 'no diff in the given range'}).")

    # the diff is the lens's scoping map; head/base copies are the full-file context
    if mode == "staged":
        diff_text = _git(repo, "diff", "--cached")
    elif mode == "worktree":
        diff_text = _git(repo, "diff", "HEAD")
    else:
        diff_text = _git(repo, "diff", f"{base}...{head}")
    open(os.path.join(rundir, "diff.patch"), "w").write(diff_text)
    new_ranges = diff_new_ranges(diff_text)

    head_ref = head if mode == "range" else (":" if mode == "staged" else None)
    manifest_files, symbol_index, trace_names = [], {}, set()
    python_changed = [path for _status, path in files if path.endswith(".py")]
    for status, path in files:
        entry = {"path": path, "status": status, "python": path.endswith(".py")}
        manifest_files.append(entry)
        if not entry["python"]:
            continue
        head_text = None if status == "D" else _blob(repo, head_ref, path)
        base_text = None if status == "A" else _blob(repo, merge_base, path)
        if head_text is not None:
            os.makedirs(os.path.dirname(os.path.join(rundir, "head", path)), exist_ok=True)
            open(os.path.join(rundir, "head", path), "w").write(head_text)
            _write_stripped(head_text, os.path.join(rundir, "head_stripped", path))
            symbols = changed_symbols(head_text, new_ranges.get(path, []))
            symbol_index[path] = symbols
            trace_names.update(s.split(".")[-1] for s in symbols if not s.startswith("<"))
        if base_text is not None:
            _write_stripped(base_text, os.path.join(rundir, "base_stripped", path))
            if head_text is not None:
                removed = top_level_names(base_text) - top_level_names(head_text)
            else:
                removed = top_level_names(base_text)
            if removed:
                symbol_index.setdefault(path, []).extend(sorted(f"removed:{n}" for n in removed))
                trace_names.update(removed)
        trace_names.add(os.path.splitext(os.path.basename(path))[0])
    trace_names = {n for n in trace_names if not n.startswith("_") and len(n) > 2}
    json.dump(symbol_index, open(os.path.join(rundir, "changed_symbols.json"), "w"), indent=1)

    n_usages = stage_usages(repo, mode, head, trace_names,
                            {path for _status, path in files}, rundir)

    # tests: union of every changed file's located tests, fenced per source file
    test_paths = sorted({t for path in python_changed
                         if os.path.exists(os.path.join(repo, path))
                         for t in find_tests(os.path.join(repo, path))})
    with open(os.path.join(rundir, "tests.py"), "w") as out:
        if not test_paths:
            out.write("# NO-TESTS MARKER: no test files were found for the changed modules.\n"
                      "# Treat the change-set's behaviors as UNVERIFIED.\n")
        for path in test_paths:
            out.write(f"\n# ===== {path} =====\n")
            out.write(open(path, encoding="utf-8", errors="replace").read())
            out.write("\n")

    open(os.path.join(rundir, "intent.txt"), "w").write(
        build_intent(repo, mode, base, head, intent_arg))
    if facts:
        shutil.copy(facts, os.path.join(rundir, "FEATURE_FACTS.md"))
    open(os.path.join(rundir, "voice_persona.txt"), "w").write(voice_persona(voice))

    label = f"{base}...{head}" if mode == "range" else f"{mode} vs HEAD"
    manifest = {"mode": mode, "base": base, "head": head, "merge_base": merge_base,
                "label": label, "repo": repo, "files": manifest_files,
                "n_python": len(python_changed), "n_usage_files": n_usages,
                "tests_found": test_paths}
    json.dump(manifest, open(os.path.join(rundir, "manifest.json"), "w"), indent=1)

    if stage_only:
        print("=== STAGING COMPLETE (--stage-only; no evaluation ran) ===")
        print(f"  rundir: {rundir}")
        print(f"  change-set: {label}   files: {len(manifest_files)} "
              f"({len(python_changed)} python)   usage files staged: {n_usages}")
        print(f"  tests found: {len(test_paths)}")
        return

    # the evaluation workflow, one clean-room claude -p
    wf_src = open(os.path.join(SKILL, "branch_wf.js")).read().replace("__RUNDIR__", rundir)
    open(os.path.join(rundir, "branch_wf.js"), "w").write(wf_src)
    claude_p_workflow(rundir, "branch_wf.js")

    # collect
    def _load(name, default):
        path = os.path.join(rundir, name)
        return json.load(open(path)) if os.path.exists(path) else default

    evaluation = _load("eval.json", {"findings": [], "domain_facts": []})
    if isinstance(evaluation, list):
        evaluation = {"findings": evaluation, "domain_facts": []}
    validation = _load("validation.json", {})
    summary = _load("summary.json", {"module_summary": "", "symbols": []})
    patches = _load("patches.json", {"patches": []})
    written = _load("written.json", {"findings": []})
    findings = evaluation.get("findings", [])
    converged = not (validation.get("any_unreal") or validation.get("any_fix_unsound"))

    def _count(key):
        out = {}
        for finding in findings:
            out[finding.get(key)] = out.get(finding.get(key), 0) + 1
        return out

    n_repros = write_repros(rundir, patches)
    phase1 = {"target": label, "mode": mode, "rundir": rundir, "voice": voice or "plain",
              "converged": converged, "n_findings": len(findings),
              "n_written": len(written.get("findings", [])),
              "n_patches": len(patches.get("patches", [])),
              "n_repros": n_repros,
              "by_angle": _count("angle"), "by_severity": _count("severity"),
              "files": [e["path"] for e in manifest_files], "tests_found": test_paths,
              "n_symbols": len(summary.get("symbols", [])),
              "eval_json": os.path.join(rundir, "eval.json"),
              "written_json": os.path.join(rundir, "written.json"),
              "summary_json": os.path.join(rundir, "summary.json"),
              "validation_json": os.path.join(rundir, "validation.json"),
              "patches_json": os.path.join(rundir, "patches.json")}
    json.dump(phase1, open(os.path.join(rundir, "phase1.json"), "w"), indent=2)

    print("=== BRANCH AUDIT PHASE COMPLETE ===")
    print(f"  rundir: {rundir}")
    print(f"  change-set: {label}   voice: {voice or 'plain'}")
    print(f"  files: {len(manifest_files)} changed ({len(python_changed)} python)   "
          f"usage files staged: {n_usages}")
    print(f"  tests found: {len(test_paths)}"
          + ("" if test_paths else "  (none -> coverage lens treats the changes as unverified)"))
    print(f"  findings: {len(findings)}   by angle: {phase1['by_angle']}   "
          f"by severity: {phase1['by_severity']}")
    print(f"  prose written: {phase1['n_written']}   patches generated: {phase1['n_patches']}   "
          f"executable repros: {n_repros}")
    print(f"  validator: {'converged clean' if converged else 'left some findings unconfirmed (report flags them)'}")
    print("  Next (in-session): render_branch.py to build + open the HTML, then the selection/apply loop.")


if __name__ == "__main__":
    main()
