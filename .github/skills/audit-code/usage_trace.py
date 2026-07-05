#!/usr/bin/env python3
"""audit skills — transitive usage-path tracer + path-finding merge (shared pipeline piece).

trace: walk the call graph OUTWARD from seed symbols — direct callers, then the callers of those
callers — across one or more repo roots (the audited repo, plus any consumer repos the user
names), until a barrier: a depth or total-file cap, each recorded under `stops` in the output so
the judging lens knows its horizon instead of guessing past it. Callers are RESOLVED, not
name-matched: each seed is anchored to its actual definition (file + line), and every candidate
site a fast word-grep turns up is confirmed with jedi's `goto` — a site counts as a caller only
when it resolves back to that exact definition. So a generic name (`tick`, `run`, `handle`) traces
to its real call sites like any other symbol instead of hitting a name cap and going dark: the
grep is only a candidate finder, jedi decides. Method call sites are grouped under their owning
top-level symbol (the `seed` field on each edge) so the judge fan-out stays per-symbol while the
edges carry method precision and the exact `call_sites`. No stripping, no clean room — this feeds
the in-session usage-path lens, which deliberately reads full commented code with project context
(the clean-room lenses stay the unbiased base; this lens trades blindness for reach along the real
integration path).

merge: append the path lens's findings (fragments + prose, composed in-session) onto a run
room's eval.json / written.json / patches.json with fresh ids and an `in_session` flag the
renderers surface, and write the lens's feature map to path_features.json — one decision page
then carries the clean-room and the path findings together, and the existing selection/apply
machinery works on all of them.

validate: the blind cross-check — stage every traced file comment-stripped under
<rundir>/path_world/ and run ONE clean-room `claude -p` (isolation flags, no project context, no
prose to anchor on) that re-checks each path finding's fragments against the stripped sources.
The full blind lens battery re-dispatched over the path would cost a clean-room run per traced
area and mostly find the callers' own at-rest defects; this single blind checker buys the part
that matters — an unbiased verdict on what the in-session lens claims. merge folds its verdicts
into the room's validation.json, so a refuted path finding defaults to discuss like any
unconfirmed finding.

Usage:
  usage_trace.py trace --root <repo> [--root <consumer-repo> ...] [--depth N] [--out <file>]
                       (--seed <name> ... | --seed-file <target.py> | --seeds-from <changed_symbols.json>)
  usage_trace.py validate <rundir> <path_findings.json>   # optional, before merge
  usage_trace.py merge <rundir> <path_findings.json>

trace needs `jedi` (pinned in requirements-dev.txt; `python scripts/run.py setup` installs it into
the repo venv). merge and validate do not import it.
"""
import ast
import glob
import json
import os
import re
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)

MAX_DEPTH = 4              # past ~4 hops a chain is architecture, not the behavior under audit
MAX_TOTAL_FILES = 40       # same horizon as the room's usage staging cap; recorded, never guessed past
SKIP_DIRS = ("tests/", "functional_tests/", ".scratch/", ".tools/", ".venv/",
             "__pycache__/", "node_modules/")


def _read_text(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _write_text(path, text):
    with open(path, "w") as handle:
        handle.write(text)


def _dump_json(payload, path):
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=1)


def _load_json(path):
    with open(path) as handle:
        return json.load(handle)


def _load_jedi():
    try:
        import jedi
    except ModuleNotFoundError:
        sys.exit("usage_trace.py trace needs `jedi` for reference resolution — it is pinned in "
                 "requirements-dev.txt; run `python scripts/run.py setup` (or `pip install "
                 "jedi==0.20.0` into the repo venv). merge/validate do not need it.")
    return jedi


# --- AST helpers: seed enumeration + enclosing-def lookup (no jedi needed) ---

def _iter_defs(tree):
    """Yield (qualname, leaf_name, node) for every def/class in the tree, nested included."""
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                yield qual, child.name, child
                yield from walk(child, qual + ".")
    yield from walk(tree, "")


def api_seed_quals(path):
    """A whole-file audit's trace surface: the public API a caller can reach — top-level public
    classes and functions, plus the public methods of those classes — each as a qualname."""
    try:
        source = _read_text(path)
    except OSError:
        return []
    return api_seed_quals_from_source(source)


def api_seed_quals_from_source(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    quals = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            quals.append(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            quals.append(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and not sub.name.startswith("_"):
                    quals.append(f"{node.name}.{sub.name}")
    return quals


def def_line_of_qual(tree, qual):
    for cand_qual, _leaf, node in _iter_defs(tree):
        if cand_qual == qual:
            return node.lineno
    return None


def enclosing_def(tree, lineno):
    """(qualname, def_line) of the innermost def/class enclosing `lineno`, or None at module level."""
    found = [None]

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = child.lineno
                end = getattr(child, "end_lineno", start) or start
                if start <= lineno <= end:
                    qual = prefix + child.name
                    found[0] = (qual, start)      # descend further; the deepest encloser wins
                    walk(child, qual + ".")
    walk(tree, "")
    return found[0]


# --- candidate finding: fast word-grep, jedi confirms which candidates are real references ---

def discover_sys_path(roots):
    """Import roots jedi needs so a caller's `from pkg import X` resolves to the real definition:
    each root plus every `src/` dir under it (the monorepo's `<lib>/src` layout)."""
    paths = []
    for root in roots:
        if os.path.isdir(root):
            paths.append(root)
        for depth in (1, 2, 3):
            paths += glob.glob(os.path.join(root, *(["*"] * depth), "src"))
    seen, out = set(), []
    for path in paths:
        real = os.path.realpath(path)
        if os.path.isdir(real) and real not in seen:
            seen.add(real)
            out.append(real)
    return out


def _fs_grep(root, name):
    """git-grep fallback for a root that is not a git worktree."""
    word = re.compile(r"\b" + re.escape(name) + r"\b")
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if (d + "/") not in SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            full = os.path.join(dirpath, filename)
            rel = os.path.relpath(full, root)
            try:
                with open(full, encoding="utf-8", errors="replace") as handle:
                    for i, line in enumerate(handle, 1):
                        if word.search(line):
                            hits.append(f"{rel}:{i}:{line.rstrip()}")
            except OSError:
                continue
    return hits


def grep_candidates(root, name):
    """(relpath, lineno) sites where the word `name` appears, skipping SKIP_DIRS. Candidates only —
    jedi decides which actually reference the seed. No cap: a generic name just means more to check."""
    try:
        result = subprocess.run(["git", "grep", "-n", "-w", name, "--", "*.py"],
                                cwd=root, capture_output=True, text=True)
        lines = result.stdout.splitlines() if result.returncode in (0, 1) else None
    except OSError:
        lines = None
    if lines is None:
        lines = _fs_grep(root, name)
    out = []
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        rel = parts[0]
        if any(seg in rel for seg in SKIP_DIRS):
            continue
        out.append((rel, int(parts[1])))
    return out


def _resolves_to(target, def_file_real, def_line):
    path = target.module_path
    if path is None:
        return False
    return os.path.realpath(str(path)) == def_file_real and target.line == def_line


def confirm_callers(jedi, project, root, leaf, def_file_real, def_line, script_cache):
    """{relpath: [(lineno, line_text), ...]} — the sites in `root` where `leaf` actually resolves
    (via jedi goto) to the definition at (def_file_real, def_line), the definition site excluded."""
    sites = {}
    for rel, lineno in grep_candidates(root, leaf):
        path = os.path.join(root, rel)
        try:
            source_lines = _read_text(path).splitlines()
        except OSError:
            continue
        if not 1 <= lineno <= len(source_lines):
            continue
        if os.path.realpath(path) == def_file_real and lineno == def_line:
            continue
        line = source_lines[lineno - 1]
        script = script_cache.get(path)
        if script is None:
            script = script_cache[path] = jedi.Script(path=path, project=project)
        for match in re.finditer(r"\b" + re.escape(leaf) + r"\b", line):
            try:
                targets = script.goto(lineno, match.start() + 1, follow_imports=True)
            except Exception:               # jedi raises assorted internal errors on odd sources
                continue
            if any(_resolves_to(t, def_file_real, def_line) for t in targets):
                sites.setdefault(rel, []).append((lineno, line.strip()))
                break
    return sites


def _root_for(path, roots):
    real = os.path.realpath(path)
    for root in roots:
        root_real = os.path.realpath(root)
        if real == root_real or real.startswith(root_real + os.sep):
            return root
    return roots[0]


def _find_named_defs(root, name):
    """(abs_path, def_line, qualname) for every def/class named `name` under `root` — the anchor
    for a bare `--seed name` when no defining file was handed in."""
    out, scanned = [], set()
    for rel, _lineno in grep_candidates(root, name):
        if rel in scanned:
            continue
        scanned.add(rel)
        path = os.path.join(root, rel)
        try:
            tree = ast.parse(_read_text(path))
        except (SyntaxError, OSError):
            continue
        for qual, leaf, node in _iter_defs(tree):
            if leaf == name:
                out.append((path, node.lineno, qual))
    return out


def resolve_seeds(seed_specs, roots):
    """Anchor each seed spec to concrete definition(s). Returns (frontier, stops). A frontier item
    carries its judge-fan-out `group` (top-level symbol), the display `label` (qualname), the
    `leaf` to grep, and the definition's real path / relpath / root / line."""
    frontier, stops, seen = [], [], set()

    def add(def_abs, def_line, label, root):
        real = os.path.realpath(def_abs)
        if (real, def_line) in seen:
            return
        seen.add((real, def_line))
        frontier.append({
            "group": label.split(".")[0], "label": label, "leaf": label.split(".")[-1],
            "def_file_real": real, "def_rel": os.path.relpath(def_abs, root),
            "def_root": root, "def_line": def_line,
        })

    for spec in seed_specs:
        if spec["kind"] == "qual":
            path, root = spec["file"], _root_for(spec["file"], roots)
            try:
                tree = ast.parse(_read_text(path))
            except (SyntaxError, OSError):
                stops.append({"seed": spec["qual"], "root": root,
                              "reason": f"seed file {os.path.basename(path)} did not parse"})
                continue
            line = def_line_of_qual(tree, spec["qual"])
            if line is None:
                stops.append({"seed": spec["qual"], "root": root,
                              "reason": f"no def named {spec['qual']} in {os.path.basename(path)} "
                                        f"(removed on this branch?) — references cannot be resolved"})
                continue
            add(path, line, spec["qual"], root)
        else:
            located = False
            for root in roots:
                for def_abs, def_line, qual in _find_named_defs(root, spec["name"]):
                    add(def_abs, def_line, qual, root)
                    located = True
            if not located:
                stops.append({"seed": spec["name"], "root": "",
                              "reason": f"no definition of {spec['name']} found in any root"})
    return frontier, stops


def cmd_trace(roots, seed_specs, depth_cap, out_path):
    jedi = _load_jedi()
    sys_path = discover_sys_path(roots)
    projects = {root: jedi.Project(root, added_sys_path=sys_path) for root in roots}
    caches = {root: {} for root in roots}

    frontier, stops = resolve_seeds(seed_specs, roots)
    seed_groups = sorted({item["group"] for item in frontier})
    edges = []
    files_seen = {(item["def_root"], item["def_rel"]) for item in frontier}
    visited = {(item["def_file_real"], item["def_line"]) for item in frontier}
    capped = False

    for depth in range(1, depth_cap + 1):
        next_frontier = []
        for item in frontier:
            if capped:
                break
            for root in roots:
                if capped:
                    break
                sites = confirm_callers(jedi, projects[root], root, item["leaf"],
                                        item["def_file_real"], item["def_line"], caches[root])
                for rel in sorted(sites):
                    if (root, rel) not in files_seen and len(files_seen) >= MAX_TOTAL_FILES:
                        stops.append({"seed": item["group"], "root": root,
                                      "reason": f"total-file cap ({MAX_TOTAL_FILES}) reached — "
                                                f"more callers of {item['label']} lie beyond it"})
                        capped = True
                        break
                    files_seen.add((root, rel))
                    try:
                        tree = ast.parse(_read_text(os.path.join(root, rel)))
                    except (SyntaxError, OSError):
                        tree = None
                    buckets = {}
                    for lineno, snippet in sites[rel]:
                        caller = enclosing_def(tree, lineno) if tree else None
                        caller_qual, caller_start = caller if caller else ("<module>", 0)
                        buckets.setdefault((caller_qual, caller_start), []).append(
                            {"line": lineno, "text": snippet})
                    for (caller_qual, caller_start), call_sites in sorted(buckets.items()):
                        edges.append({
                            "seed": item["group"], "callee": item["label"],
                            "callee_file": item["def_rel"], "caller_qual": caller_qual,
                            "caller_file": rel, "root": root, "depth": depth,
                            "call_sites": sorted(call_sites, key=lambda site: site["line"]),
                        })
                        caller_real = os.path.realpath(os.path.join(root, rel))
                        if caller_qual != "<module>" and (caller_real, caller_start) not in visited:
                            visited.add((caller_real, caller_start))
                            next_frontier.append({
                                "group": item["group"], "label": caller_qual,
                                "leaf": caller_qual.split(".")[-1], "def_file_real": caller_real,
                                "def_rel": rel, "def_root": root, "def_line": caller_start,
                            })
        if capped or not next_frontier:
            break
        frontier = next_frontier
    else:
        if frontier:
            stops.append({"seed": "", "root": "",
                          "reason": f"depth cap ({depth_cap}) reached with the frontier still live"})

    payload = {"roots": roots, "seeds": seed_groups,
               "caps": {"depth": depth_cap, "total_files": MAX_TOTAL_FILES},
               "edges": edges,
               "files": sorted(f"{root}:{rel}" for root, rel in files_seen),
               "stops": stops}
    _dump_json(payload, out_path)
    print(f"TRACED {len(edges)} edges across {len(files_seen)} files "
          f"({len(stops)} stop(s) recorded) -> {out_path}")
    print(f"  seeds: {', '.join(seed_groups) if seed_groups else '(none resolved)'}")
    return 0


VALIDATE_PROMPT = (
    "Read the comment-stripped sources under ./path_world/ (listed in ./path_world_manifest.txt; "
    "read each one) and the numbered findings in ./path_findings_check.json — refer to each by "
    "its 0-based `index`. You have NO prior knowledge of this code; the sources are the only "
    "truth. For EACH finding decide two things: real (the `defect` is actually true against "
    "these sources AND the `bite` is not overstated) and fix_sound (the `fix` would work without "
    "breaking behavior). Write JSON "
    '{"findings": [{"index": N, "real": bool, "fix_sound": bool, "note": "short reason"}]} '
    "covering every index to ./path_validation.json, then reply DONE."
)


def cmd_validate(rundir, findings_path):
    from preflight import require_claude
    from strip import strip_code
    require_claude()
    paths_file = os.path.join(rundir, "usage_paths.json")
    if not os.path.exists(paths_file):
        sys.exit(f"no usage_paths.json in {rundir} — run trace with --out into the room first")
    payload = _load_json(findings_path)
    if not payload.get("findings"):
        print("no path findings to validate")
        return 0

    world = os.path.join(rundir, "path_world")
    manifest = []
    for entry in _load_json(paths_file).get("files", []):
        root, rel = entry.split(":", 1)
        source_path = os.path.join(root, rel)
        if not os.path.exists(source_path):
            continue
        dest = os.path.join(world, os.path.basename(root.rstrip("/")), rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        text = _read_text(source_path)
        try:
            _write_text(dest, strip_code(text))
        except SyntaxError:
            _write_text(dest, text)
        manifest.append(os.path.relpath(dest, rundir))
    _write_text(os.path.join(rundir, "path_world_manifest.txt"), "\n".join(manifest) + "\n")

    # fragments only — the checker re-derives from code; the composed prose would hand it a
    # fluent claim to anchor on, the bias the blind check exists to escape
    check = {"findings": [
        {"index": i, "file": f.get("file", ""), "symbol": f.get("symbol", ""),
         "site": f.get("site", ""), "defect": f.get("defect", ""),
         "bite": f.get("bite", ""), "fix": f.get("fix", "")}
        for i, f in enumerate(payload["findings"])]}
    _dump_json(check, os.path.join(rundir, "path_findings_check.json"))

    from audit_phase1 import CLEAN_ROOM_SETTINGS
    completed = subprocess.run(["claude", "--setting-sources", "project,local", "--strict-mcp-config",
                                "--disable-slash-commands", "-p", VALIDATE_PROMPT,
                                "--allowedTools", "Read", "Write",
                                "--permission-mode", "acceptEdits", "--model", "opus",
                                "--output-format", "json", "--settings", CLEAN_ROOM_SETTINGS],
                               cwd=rundir, capture_output=True, text=True)
    try:
        envelope = json.loads(completed.stdout or "")
    except ValueError:
        envelope = {"unparseable_stdout_tail": (completed.stdout or "")[-2000:]}
    envelope["stderr_tail"] = (completed.stderr or "")[-2000:]
    _dump_json(envelope, os.path.join(rundir, "validate_claude_envelope.json"))
    out = os.path.join(rundir, "path_validation.json")
    if os.path.exists(out):
        verdicts = _load_json(out).get("findings", [])
        refuted = [v for v in verdicts if not v.get("real", True)]
        print(f"BLIND CHECK: {len(verdicts)} finding(s) checked, {len(refuted)} refuted "
              f"-> {out}")
    else:
        print("WARNING: path_validation.json not produced — merge will mark every path finding "
              "as unvalidated (in-session marker only)")
    return 0


def cmd_merge(rundir, findings_path):
    payload = _load_json(findings_path)

    def load(name, default):
        path = os.path.join(rundir, name)
        return _load_json(path) if os.path.exists(path) else default

    evaluation = load("eval.json", {"findings": [], "domain_facts": []})
    if isinstance(evaluation, list):
        evaluation = {"findings": evaluation, "domain_facts": []}
    written = load("written.json", {"findings": []})
    patches = load("patches.json", {"patches": []})
    validation = load("validation.json", {"findings": [], "any_unreal": False,
                                          "any_fix_unsound": False, "verdict": ""})
    blind = {v.get("index"): v
             for v in load("path_validation.json", {"findings": []}).get("findings", [])}

    next_id = max((f.get("id", 0) for f in evaluation["findings"]), default=0) + 1
    added = []
    for index, finding in enumerate(payload.get("findings", [])):
        fid = next_id
        next_id += 1
        evaluation["findings"].append({
            "id": fid, "angle": "path", "in_session": True,
            "file": finding.get("file", ""), "symbol": finding.get("symbol", "?"),
            "site": finding.get("site", ""), "feature": finding.get("feature", ""),
            "severity": finding.get("severity", "med"), "effort": finding.get("effort", "medium"),
            "confidence": finding.get("confidence", "med"),
            "defect": finding.get("defect", ""), "bite": finding.get("bite", ""),
            "fix": finding.get("fix", ""),
        })
        written["findings"].append({
            "id": fid, "title": finding.get("title", ""),
            "consequence": finding.get("consequence", ""),
            "problem": finding.get("problem", ""),
            "suggested_fix": finding.get("suggested_fix", ""),
        })
        patches["patches"].append({
            "id": fid, "file": finding.get("file", ""), "kind": "manual",
            "before": "", "after": "",
            "location_hint": f"{finding.get('file', '')} · {finding.get('symbol', '')}",
            "note": finding.get("suggested_fix", ""), "repro": "",
        })
        # fold the blind clean-room verdict (cmd_validate, indexed) in under the assigned id, so
        # a refuted path finding gets the standard unconfirmed treatment on the page
        if index in blind:
            verdict = blind[index]
            validation["findings"].append({
                "id": fid, "real": bool(verdict.get("real", True)),
                "fix_sound": bool(verdict.get("fix_sound", True)),
                "note": f"(blind path check) {verdict.get('note', '')}".strip(),
            })
            validation["any_unreal"] = validation.get("any_unreal", False) or not verdict.get("real", True)
            validation["any_fix_unsound"] = (validation.get("any_fix_unsound", False)
                                             or not verdict.get("fix_sound", True))
        added.append(fid)

    _dump_json(evaluation, os.path.join(rundir, "eval.json"))
    _dump_json(written, os.path.join(rundir, "written.json"))
    _dump_json(patches, os.path.join(rundir, "patches.json"))
    _dump_json(validation, os.path.join(rundir, "validation.json"))
    if payload.get("features"):
        _dump_json({"features": payload["features"]},
                   os.path.join(rundir, "path_features.json"))
    print(f"MERGED {len(added)} path finding(s) into {rundir} "
          f"(ids {added[0]}..{added[-1]})" if added else "MERGED 0 path findings")
    if payload.get("features"):
        print(f"  feature map: {len(payload['features'])} feature(s) -> path_features.json")
    print("  re-render the page so the new cards appear.")
    return 0


def main():
    args = sys.argv[1:]
    if args[:1] == ["merge"] and len(args) == 3:
        sys.exit(cmd_merge(os.path.abspath(args[1]), args[2]))
    if args[:1] == ["validate"] and len(args) == 3:
        sys.exit(cmd_validate(os.path.abspath(args[1]), args[2]))
    if args[:1] != ["trace"]:
        sys.exit(__doc__.strip().split("Usage:")[1].strip())

    def values(flag):
        return [args[i + 1] for i, a in enumerate(args) if a == flag]

    roots = [os.path.abspath(r) for r in values("--root")]

    # Seed specs anchor each seed to its definition. A `qual` spec carries the defining file, so the
    # reference resolver goes straight to the exact def; a `name` spec is a bare symbol the resolver
    # locates across the roots. `--seeds-from` (a branch's {file: [qualnames]}) keeps the file->qual
    # mapping the old leaf-only path threw away, so a changed `Runner.tick` anchors to its own file.
    seed_specs = [{"kind": "name", "name": name} for name in values("--seed")]
    for seed_file in values("--seed-file"):
        for qual in api_seed_quals(seed_file):
            seed_specs.append({"kind": "qual", "file": seed_file, "qual": qual})
    for symbols_json in values("--seeds-from"):
        index = _load_json(symbols_json)
        for file_rel, quals in index.items():
            defining_file = next((os.path.join(root, file_rel) for root in roots
                                  if os.path.exists(os.path.join(root, file_rel))), None)
            for qual in quals:
                clean = qual.split(":")[-1]                 # drop removed:/added: prefixes
                if clean.startswith("<") or len(clean.split(".")[-1]) <= 2:
                    continue
                if defining_file:
                    seed_specs.append({"kind": "qual", "file": defining_file, "qual": clean})
                else:
                    seed_specs.append({"kind": "name", "name": clean.split(".")[-1]})

    depth = int(values("--depth")[0]) if values("--depth") else MAX_DEPTH
    out = values("--out")[0] if values("--out") else "usage_paths.json"
    if not roots or not seed_specs:
        sys.exit("trace needs at least one --root and one seed "
                 "(--seed / --seed-file / --seeds-from)")
    sys.exit(cmd_trace(roots, seed_specs, depth, out))


if __name__ == "__main__":
    main()
