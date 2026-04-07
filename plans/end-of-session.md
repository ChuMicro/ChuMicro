# End-of-session checklist

Use this checklist at the end of every working session to ensure the workspace
is clean and planning docs are current.

## 1. Run preflight

```zsh
python scripts/run.py preflight
```

Do not commit code that fails lint, tests, or build.

## 2. Check for uncommitted work

```zsh
git status --short
```

If there are uncommitted changes, stage and commit them before proceeding.

## 3. Check VERSION bumps

If any library under `libraries/` was changed (this session or in unpushed
commits from a prior session), check whether the change affects the published
surface area (new API, changed behavior, bug fix).  If so, verify the
library's `VERSION` file was bumped with the smallest correct semantic-version
increment.

## 4. Check IDE configs

If any library or support package was added or removed, run
`python scripts/run.py sync-ide` to regenerate PyCharm and VS Code configs.
(`new-library` calls this automatically, but manual structural changes can
leave configs stale.)

## 5. Audit planning docs

Scan `git log --oneline -20` for commits that added, removed, or renamed
libraries, APIs, decisions, or workspace structure.  For each significant
change, verify:

| File | What to verify |
|---|---|
| `plans/next-up.md` | Checked-off items moved to Done; new work added |
| `plans/roadmap.md` | Milestone status reflects actual state |
| `plans/history.md` | Timeline entry added for the current session (if significant) |
| `plans/decisions/` | New decisions recorded if tradeoffs were made |

## 6. Commit with good messages

Write commit messages that aid context recovery — summarise *what* in the
subject, explain *why* in the body when non-trivial, and name affected
libraries or decisions.  See `.github/skills/git-commit/SKILL.md` for
commit mechanics.

## 7. Verify clean tree

```zsh
git status --short
```

Should produce no output.

