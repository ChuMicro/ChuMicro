#!/usr/bin/env python3
"""Routing probes for a skill's trigger-evals.json (shared across skills).

Each query fires a fresh `claude -p --max-turns 1` from the repo root, so the probe
sees the real skill registry: every sibling description competes for the route, the
way it does in production. The prompt asks a routing question only (which skill would
you invoke for this request), never executes the task; a majority vote across --runs
decides each query.

A positive query (should_trigger true) passes when the majority answer is the evals
file's skill_name. A negative query passes when the majority answer is anything else;
when the row carries expected_route, the result records whether the majority matched
it, as information for the reader -- the pass/fail contract is only about the skill
under test.

Usage: run_trigger_evals.py <trigger-evals.json> [--runs 3] [--workers 4]
                            [--limit N] [--out <results.json>]
--limit N probes only the first N queries (a cheap smoke before a full sweep).
Exit 0 = every query passed; exit 1 = at least one failed or was unparseable.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROUTING_PROMPT = (
    "You are being asked a routing question only. Do not perform the task and "
    "do not invoke any tools. From your available skills list, which skill (if "
    "any) would you invoke for the following user request? Answer with exactly "
    "one token: the skill slug, or none.\n\nUser request: {query}"
)


def find_repo_root(start):
    """Nearest ancestor of `start` holding a .git or .claude dir (the claude -p cwd)."""
    directory = os.path.abspath(start)
    while True:
        if any(os.path.isdir(os.path.join(directory, marker)) for marker in (".git", ".claude")):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            sys.exit(f"no .git or .claude dir above {start} -- run from inside a repo.")
        directory = parent


def known_slugs(repo_root, evals):
    """Every slug the answer extractor should recognize, longest first.

    Longest-first matters: an answer that mentions two slugs ("not regen-comments,
    audit-docs") resolves to the more specific match instead of a prefix.
    """
    slugs = {"none", evals.get("skill_name", "")}
    for tree in (".github/skills", ".claude/skills"):
        base = os.path.join(repo_root, tree)
        if os.path.isdir(base):
            for entry in os.listdir(base):
                if os.path.exists(os.path.join(base, entry, "SKILL.md")):
                    slugs.add(entry)
    for row in evals.get("evals", []):
        if row.get("expected_route"):
            slugs.add(row["expected_route"])
    return sorted((s for s in slugs if s), key=len, reverse=True)


def extract_slug(text, slugs):
    lowered = text.strip().lower()
    for slug in slugs:
        if re.search(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", lowered):
            return slug
    return f"unparsed:{lowered[:60]}"


def probe(query, slugs, repo_root):
    """One routing probe: a fresh claude -p answering which skill it would invoke."""
    try:
        completed = subprocess.run(
            ["claude", "-p", "--max-turns", "1", ROUTING_PROMPT.format(query=query)],
            cwd=repo_root, capture_output=True, text=True, timeout=240,
        )
    except subprocess.TimeoutExpired:
        return "error:timeout"
    return extract_slug(completed.stdout or completed.stderr, slugs)


def main():
    parser = argparse.ArgumentParser(description="Routing probes for a trigger-evals.json")
    parser.add_argument("evals_path")
    parser.add_argument("--runs", type=int, default=3, help="probes per query (majority vote)")
    parser.add_argument("--workers", type=int, default=4, help="parallel claude -p processes")
    parser.add_argument("--limit", type=int, default=0, help="probe only the first N queries")
    parser.add_argument("--out", default="", help="results JSON path (default .scratch/trigger-evals/)")
    arguments = parser.parse_args()

    evals_path = os.path.abspath(arguments.evals_path)
    data = json.load(open(evals_path))
    skill_name = data.get("skill_name") or os.path.basename(os.path.dirname(evals_path))
    rows = data["evals"][: arguments.limit] if arguments.limit else data["evals"]
    repo_root = find_repo_root(os.path.dirname(evals_path))
    slugs = known_slugs(repo_root, data)

    total_probes = len(rows) * arguments.runs
    print(f"probing {len(rows)} queries x {arguments.runs} run(s) = {total_probes} "
          f"claude -p calls ({arguments.workers} parallel, ~15-60s each)...", flush=True)

    started = time.time()
    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        jobs = {}
        for index, row in enumerate(rows):
            for run_number in range(arguments.runs):
                jobs[(index, run_number)] = pool.submit(probe, row["query"], slugs, repo_root)
        answers = {}
        for (index, run_number), job in jobs.items():
            slug = job.result()
            answers.setdefault(index, []).append(slug)
            print(f"  q{index} run{run_number}: {slug}", flush=True)

    majority_needed = arguments.runs // 2 + 1
    results, failed = [], 0
    for index, row in enumerate(rows):
        majority_slug, majority_count = Counter(answers[index]).most_common(1)[0]
        routed_here = majority_slug == skill_name and majority_count >= majority_needed
        passed = routed_here if row["should_trigger"] else (
            majority_count >= majority_needed and majority_slug != skill_name)
        expected_route = row.get("expected_route", "")
        results.append({
            "query": row["query"], "should_trigger": row["should_trigger"],
            "expected_route": expected_route, "answers": answers[index],
            "majority": majority_slug, "pass": passed,
            "expected_route_match": bool(expected_route) and majority_slug == expected_route,
        })
        failed += 0 if passed else 1
        marker = "PASS" if passed else "FAIL"
        route_note = f" (expected_route={expected_route}: "\
                     f"{'match' if results[-1]['expected_route_match'] else 'differs'})" \
                     if expected_route else ""
        print(f"[{marker}] {majority_slug} <- {row['query'][:70]}{route_note}", flush=True)

    out_path = arguments.out or os.path.join(
        repo_root, ".scratch", "trigger-evals",
        f"{skill_name}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump({"skill_name": skill_name, "runs": arguments.runs, "results": results},
              open(out_path, "w"), indent=1)
    print(f"=== TRIGGER EVALS: {len(rows) - failed}/{len(rows)} passed "
          f"in {time.time() - started:.0f}s -> {out_path} ===")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
