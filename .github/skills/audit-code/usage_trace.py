#!/usr/bin/env python3
"""audit skills — transitive usage-path tracer + path-finding merge (shared pipeline piece).

trace: walk the call graph OUTWARD from seed symbols — direct callers, then the callers of those
callers — across one or more repo roots (the audited repo, plus any consumer repos the user
names), until a barrier: depth, total-file, or generic-name caps, each recorded under `stops` in
the output so the judging lens knows its horizon instead of guessing past it. No stripping, no
clean room — this feeds the in-session usage-path lens, which deliberately reads full commented
code with project context (the clean-room lenses stay the unbiased base; this lens trades
blindness for reach along the real integration path).

merge: append the path lens's findings (fragments + prose, composed in-session) onto a run
room's eval.json / written.json / patches.json with fresh ids and an `in_session` flag the
renderers surface, and write the lens's feature map to path_features.json — one decision page
then carries the clean-room and the path findings together, and the existing selection/apply
machinery works on all of them.

validate: the blind cross-check — stage every traced file comment-stripped under
<rundir>/path_world/ and run ONE clean-room `claude -p` (--safe-mode, no project context, no
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
"""
import ast
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)

MAX_DEPTH = 4              # past ~4 hops a chain is architecture, not the behavior under audit
MAX_TOTAL_FILES = 40       # same horizon as the room's usage staging cap; recorded, never guessed past
GENERIC_NAME_FILE_CAP = 15  # a name in >15 files is a generic verb (tick / run / handle); expanding
                            # it traces the whole repo, not the usage path — record the stop instead
SKIP_DIRS = ("tests/", "functional_tests/", ".scratch/", ".tools/", ".venv/",
             "__pycache__/", "node_modules/")


def _grep_files(root, name):
    result = subprocess.run(["git", "grep", "-l", "-w", name, "--", "*.py"],
                            cwd=root, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines()
            if not any(seg in line for seg in SKIP_DIRS)]


def enclosing_callers(source, name):
    """Qualnames of the defs whose body references `name` (plus <module> for top-level uses)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    callers = set()

    def references(node):
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == name:
                return True
            if isinstance(child, ast.Attribute) and child.attr == name:
                return True
        return False

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = prefix + child.name
                if references(child):
                    callers.add(qual)
                walk(child, qual + ".")

    walk(tree, "")
    if references(tree) and not callers:
        callers.add("<module>")
    return callers


def public_top_level_names(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except SyntaxError:
        return []
    names = [node.name for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return [n for n in names if not n.startswith("_")]


def cmd_trace(roots, seeds, depth_cap, out_path):
    edges, stops = [], []
    files_seen = set()
    visited_names = set(seeds)
    frontier = set(seeds)
    for depth in range(1, depth_cap + 1):
        next_names = set()
        for name in sorted(frontier):
            for root in roots:
                hits = _grep_files(root, name)
                if len(hits) > GENERIC_NAME_FILE_CAP:
                    stops.append({"name": name, "root": root,
                                  "reason": f"{len(hits)} files reference it — generic name, "
                                            f"expanding would trace the repo, not the path"})
                    continue
                for rel in hits:
                    if len(files_seen) >= MAX_TOTAL_FILES:
                        stops.append({"name": name, "root": root,
                                      "reason": f"total-file cap ({MAX_TOTAL_FILES}) reached"})
                        break
                    files_seen.add((root, rel))
                    source = open(os.path.join(root, rel), encoding="utf-8",
                                  errors="replace").read()
                    for qual in sorted(enclosing_callers(source, name)):
                        edges.append({"callee": name, "caller_qual": qual,
                                      "caller_file": rel, "root": root, "depth": depth})
                        leaf = qual.split(".")[-1]
                        if leaf != "<module>" and len(leaf) > 2 and leaf not in visited_names:
                            next_names.add(leaf)
        if not next_names:
            break
        visited_names |= next_names
        frontier = next_names
    else:
        stops.append({"name": "", "root": "",
                      "reason": f"depth cap ({depth_cap}) reached with the frontier still live"})

    payload = {"roots": roots, "seeds": sorted(seeds),
               "caps": {"depth": depth_cap, "total_files": MAX_TOTAL_FILES,
                        "generic_name_files": GENERIC_NAME_FILE_CAP},
               "edges": edges,
               "files": sorted(f"{root}:{rel}" for root, rel in files_seen),
               "stops": stops}
    json.dump(payload, open(out_path, "w"), indent=1)
    print(f"TRACED {len(edges)} edges across {len(files_seen)} files "
          f"({len(stops)} stop(s) recorded) -> {out_path}")
    print(f"  seeds: {', '.join(sorted(seeds))}")
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
    payload = json.load(open(findings_path))
    if not payload.get("findings"):
        print("no path findings to validate")
        return 0

    world = os.path.join(rundir, "path_world")
    manifest = []
    for entry in json.load(open(paths_file)).get("files", []):
        root, rel = entry.split(":", 1)
        source_path = os.path.join(root, rel)
        if not os.path.exists(source_path):
            continue
        dest = os.path.join(world, os.path.basename(root.rstrip("/")), rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        text = open(source_path, encoding="utf-8", errors="replace").read()
        try:
            open(dest, "w").write(strip_code(text))
        except SyntaxError:
            open(dest, "w").write(text)
        manifest.append(os.path.relpath(dest, rundir))
    open(os.path.join(rundir, "path_world_manifest.txt"), "w").write("\n".join(manifest) + "\n")

    # fragments only — the checker re-derives from code; the composed prose would hand it a
    # fluent claim to anchor on, the bias the blind check exists to escape
    check = {"findings": [
        {"index": i, "file": f.get("file", ""), "symbol": f.get("symbol", ""),
         "site": f.get("site", ""), "defect": f.get("defect", ""),
         "bite": f.get("bite", ""), "fix": f.get("fix", "")}
        for i, f in enumerate(payload["findings"])]}
    json.dump(check, open(os.path.join(rundir, "path_findings_check.json"), "w"), indent=1)

    subprocess.run(["claude", "--safe-mode", "-p", VALIDATE_PROMPT,
                    "--allowedTools", "Read", "Write",
                    "--permission-mode", "acceptEdits", "--model", "opus"],
                   cwd=rundir, capture_output=True, text=True)
    out = os.path.join(rundir, "path_validation.json")
    if os.path.exists(out):
        verdicts = json.load(open(out)).get("findings", [])
        refuted = [v for v in verdicts if not v.get("real", True)]
        print(f"BLIND CHECK: {len(verdicts)} finding(s) checked, {len(refuted)} refuted "
              f"-> {out}")
    else:
        print("WARNING: path_validation.json not produced — merge will mark every path finding "
              "as unvalidated (in-session marker only)")
    return 0


def cmd_merge(rundir, findings_path):
    payload = json.load(open(findings_path))

    def load(name, default):
        path = os.path.join(rundir, name)
        return json.load(open(path)) if os.path.exists(path) else default

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

    json.dump(evaluation, open(os.path.join(rundir, "eval.json"), "w"), indent=1)
    json.dump(written, open(os.path.join(rundir, "written.json"), "w"), indent=1)
    json.dump(patches, open(os.path.join(rundir, "patches.json"), "w"), indent=1)
    json.dump(validation, open(os.path.join(rundir, "validation.json"), "w"), indent=1)
    if payload.get("features"):
        json.dump({"features": payload["features"]},
                  open(os.path.join(rundir, "path_features.json"), "w"), indent=1)
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
    seeds = set(values("--seed"))
    for seed_file in values("--seed-file"):
        seeds.update(public_top_level_names(seed_file))
    for symbols_json in values("--seeds-from"):
        index = json.load(open(symbols_json))
        for quals in index.values():
            for qual in quals:
                leaf = qual.split(":")[-1].split(".")[-1]
                if leaf != "<module>" and len(leaf) > 2:
                    seeds.add(leaf)
    depth = int(values("--depth")[0]) if values("--depth") else MAX_DEPTH
    out = values("--out")[0] if values("--out") else "usage_paths.json"
    if not roots or not seeds:
        sys.exit("trace needs at least one --root and one seed "
                 "(--seed / --seed-file / --seeds-from)")
    sys.exit(cmd_trace(roots, sorted(seeds), depth, out))


if __name__ == "__main__":
    main()
