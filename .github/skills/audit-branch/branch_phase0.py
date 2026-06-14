#!/usr/bin/env python3
"""audit-branch — feature context pass (optional, default for multi-file change-sets).

Before judging a change-set, build one ledger describing the world it lands in: what user-facing
capability the affected packages provide, the contracts around the files about to change, and the
domain terms a reviewer needs. The staging is BASE-side on purpose — the lenses get the pre-change
world the branch integrates into, not the branch's own claims about it. Sources are
comment-stripped (clean room: context derived from behavior, not comments) and the one `claude -p`
sees the changed-file list as focus, never the diff itself.

The orchestrator passes `--facts <rundir>/FEATURE_FACTS.md` to branch_phase1.py afterward. A
small change-set (one or two files inside one package) usually skips this.

Usage:
  branch_phase0.py <base_ref> <head_ref> <rundir> [--repo <root>]
  branch_phase0.py --staged <rundir> [--repo <root>]
  branch_phase0.py --worktree <rundir> [--repo <root>]

`--stage-only` stops after laying out ./world/ (no `claude -p`) — for the TESTPLAN's fixture rows.
"""
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(os.path.dirname(SKILL), "audit-code")
sys.path.insert(0, PIPELINE)
sys.path.insert(0, SKILL)
from audit_phase1 import CLEAN_ROOM_SETTINGS  # noqa: E402
from branch_phase1 import _git, changed_files  # noqa: E402
from preflight import require_claude  # noqa: E402
from strip import strip_code  # noqa: E402

PROMPT_HEAD = (
    "Read the comment-stripped sources under ./world/ (listed in ./world_manifest.txt; read each "
    "one). A change-set is about to modify these files:\n{changed}\n\n"
    "Produce FEATURE_FACTS.md, a tight ledger a change-set reviewer needs to judge the changes "
    "without re-deriving the surrounding packages:\n"
    "- FEATURE: one short paragraph per affected package on the user-facing capability it "
    "provides — what someone builds with it, not how it is implemented.\n"
    "- CONTRACTS: the contracts around the files about to change — what each provides and "
    "expects, shared types and their meaning, invariants or protocols other files rely on "
    "(e.g. 'X returns a handle that Y must close').\n"
    "- GLOSSARY: the domain terms a reader must know, defined briefly.\n"
    "Keep it factual and derived from the code; do not invent. Write it to ./FEATURE_FACTS.md, "
    "then reply DONE."
)


def package_roots(paths):
    """The source trees worth staging for context: for a changed file under a src/ layout
    (libraries/<n>/src, support/<n>/src, workbench/<n>/src) the whole src tree; otherwise the
    file's own directory."""
    roots = set()
    for path in paths:
        parts = path.split("/")
        if "src" in parts:
            roots.add("/".join(parts[: parts.index("src") + 1]))
        else:
            roots.add(os.path.dirname(path) or ".")
    # drop roots nested inside another selected root
    return sorted(r for r in roots
                  if not any(r != other and r.startswith(other + "/") for other in roots))


def main():
    args = sys.argv[1:]
    stage_only = "--stage-only" in args
    if not stage_only:
        require_claude()
    repo = os.path.abspath(args[args.index("--repo") + 1] if "--repo" in args
                           else _git(".", "rev-parse", "--show-toplevel").strip())
    mode = "staged" if "--staged" in args else ("worktree" if "--worktree" in args else "range")
    pos = [a for a in args if not a.startswith("--")
           and a != (args[args.index("--repo") + 1] if "--repo" in args else None)]
    if mode == "range":
        if len(pos) < 3:
            sys.exit("usage: branch_phase0.py <base_ref> <head_ref> <rundir> [--repo <root>] "
                     "| --staged|--worktree <rundir> [--repo <root>]")
        base, head, rundir = pos[0], pos[1], os.path.abspath(pos[2])
        world_ref = _git(repo, "merge-base", base, head).strip()
    else:
        if len(pos) < 1:
            sys.exit("usage: branch_phase0.py --staged|--worktree <rundir> [--repo <root>]")
        base, head, rundir = "HEAD", None, os.path.abspath(pos[0])
        world_ref = "HEAD"

    changed = [path for _status, path in changed_files(repo, mode, base, head)]
    if not changed:
        sys.exit("the change-set is empty — nothing to build context for.")
    roots = package_roots([p for p in changed if p.endswith(".py")]) or ["."]

    world = os.path.join(rundir, "world")
    manifest = []
    for root in roots:
        listing = _git(repo, "ls-tree", "-r", "--name-only", world_ref, root, check=False)
        for rel in listing.splitlines():
            if not rel.endswith(".py") or "__pycache__" in rel:
                continue
            if any(seg in rel for seg in ("/tests/", "/functional_tests/", "/examples/")):
                continue
            show = subprocess.run(["git", "show", f"{world_ref}:{rel}"], cwd=repo,
                                  capture_output=True, text=True)
            if show.returncode != 0:
                continue
            dest = os.path.join(world, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                open(dest, "w").write(strip_code(show.stdout))
            except SyntaxError:
                open(dest, "w").write(show.stdout)
            manifest.append("world/" + rel)
    if not manifest:
        sys.exit(f"no python sources found under {roots} at {world_ref} — nothing to stage.")
    open(os.path.join(rundir, "world_manifest.txt"), "w").write("\n".join(manifest) + "\n")

    if stage_only:
        print(f"=== STAGING COMPLETE (--stage-only; no context pass ran) ===\n"
              f"  {len(manifest)} files staged from {len(roots)} package root(s) under {world}")
        return

    prompt = PROMPT_HEAD.format(changed="\n".join(f"- {p}" for p in changed))
    # isolation flags below; default auth preserves OAuth (--bare would force ANTHROPIC_API_KEY instead)
    completed = subprocess.run(["claude", "--setting-sources", "project,local", "--strict-mcp-config",
                                "--disable-slash-commands", "-p", prompt, "--allowedTools", "Read", "Write",
                                "--permission-mode", "acceptEdits", "--model", "opus",
                                "--output-format", "json", "--settings", CLEAN_ROOM_SETTINGS],
                               cwd=rundir, capture_output=True, text=True)
    try:
        envelope = json.loads(completed.stdout or "")
    except ValueError:
        envelope = {"unparseable_stdout_tail": (completed.stdout or "")[-2000:]}
    envelope["stderr_tail"] = (completed.stderr or "")[-2000:]
    json.dump(envelope, open(os.path.join(rundir, "claude_envelope.json"), "w"), indent=1)
    out = os.path.join(rundir, "FEATURE_FACTS.md")
    if os.path.exists(out):
        print(f"wrote {out}  ({len(manifest)} files from {len(roots)} package root(s))")
    else:
        print(f"WARNING: FEATURE_FACTS.md not produced (continuing without feature context); "
              f"{len(manifest)} files staged")


if __name__ == "__main__":
    main()
