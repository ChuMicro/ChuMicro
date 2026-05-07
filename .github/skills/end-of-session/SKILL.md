---
name: end-of-session
description: Human-driven checklist for the end of a working session. Covers preflight, VERSION bumps, IDE configs, and planning doc hygiene. Agents use task-checkpoint instead.
---

# End-of-session checklist

> **For human contributors.** Agents should use the `task-checkpoint` skill after each unit of work — it runs preflight and commits. This checklist covers broader housekeeping that humans do at the end of a working session.

Use this checklist at the end of every working session to ensure the workspace
is clean and planning docs are current.

## 1. Run preflight

```bash
python scripts/run.py preflight 2>&1 | tail -5
```

Must show: `Preflight passed — required CI checks should pass.`

If it fails, fix the issue before continuing. Use the `debug-test-failure` skill if tests fail.

## 2. Check VERSION bumps

If any library under `libraries/` was changed (this session or in unpushed
commits from a prior session), check whether the change affects the published
surface area (new API, changed behavior, bug fix).  If so, verify the
library's `VERSION` file was bumped with the smallest correct semantic-version
increment.

## 3. Check IDE configs

If any library or support package was added or removed, run
`python scripts/run.py sync-ide` to regenerate PyCharm and VS Code configs.
(`new-library` calls this automatically, but manual structural changes can
leave configs stale.)

## 4. Audit planning docs

Review recent commit history for context — we move fast, so look back far enough
to catch anything that slipped:

```bash
git --no-pager log --oneline -50
```

Then read the full messages for any commits that look like they touched
structure, APIs, decisions, or workspace layout:

```bash
git --no-pager log -50 --format="%h %s%n%b" | cat
```

For each significant change, verify:

| File | What to verify |
|---|---|
| `plans/next-up.md` | Checked-off items moved to Done; new work added |
| `plans/decisions/` | New decisions recorded if tradeoffs were made |

If you added a new task, command, library, or changed existing behavior, ask: *"If someone reads the docs tomorrow, will they find correct information about this?"* Update whatever your changes make wrong — READMEs, contributing guides, style guide, cheat sheet, CI workflows, scaffold templates, IDE configs, planning docs.

## 5. Commit remaining work

Stage and commit any uncommitted changes. Use the `git-commit` skill.

Write commit messages that aid context recovery — summarise *what* in the
subject, explain *why* in the body when non-trivial, and name affected
libraries or decisions.

## 6. Verify clean tree

```bash
git status --short
```

Should produce no output.
