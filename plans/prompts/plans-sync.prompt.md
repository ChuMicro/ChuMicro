# Prompt: Sync planning docs after workspace changes

Use this prompt when planning docs, decisions, workstreams, or prompts may have
fallen behind the actual codebase — typically at the end of a session that made
significant implementation changes.

## When to use

- After implementing a new library or major feature
- After accepting a new decision
- After changing workspace structure (new tasks in run.py, new support packages, etc.)
- When a session touched multiple areas and you suspect planning docs are stale

## Steps

1. **Gather context.** Read `git log --oneline -20` and scan the recent commits
   for what changed. Note new libraries, decisions, version bumps, and new
   task-runner commands.

2. **Scan for new artifacts.** List the contents of `plans/decisions/`,
   `plans/prompts/`, and `plans/workstreams/`. Compare against what is
   referenced in the planning docs (especially `plans/README.md`,
   `workspace-resume.prompt.md`, and `workspace-rebuild.prompt.md`). Any file
   on disk that is not referenced in an index or listing is a candidate for
   addition.

3. **Check each file against reality.** For each file below, verify that it
   reflects the current codebase. Fix anything stale.

   | File | What to check |
   |---|---|
   | `plans/README.md` | Decisions range, current planning set list (decisions, workstreams, prompts) |
   | `plans/next-up.md` | New items in Now/Next, checked-off items moved to Done |
   | `plans/roadmap.md` | Milestone progress, verified progress lists, incomplete items |
   | `plans/workstreams/*.md` | Each workstream's verified slice, resolved decisions |
   | `plans/prompts/workspace-resume.prompt.md` | Decision list, code anchors, capabilities, open areas |
   | `plans/prompts/workspace-rebuild.prompt.md` | Repo shape, required decisions, implementation slices |
   | `plans/prompts/workspace-history.prompt.md` | Timeline entry for the current session |
   | `plans/prompts/workstream-planning.prompt.md` | Decisions, code slices, commands, done/incomplete |

4. **Don't update what hasn't changed.** Only touch files where the content is
   actually stale. Avoid churn for the sake of churn.

5. **Commit the sync.** A single commit is fine. Subject line should name what
   was synced (e.g., "Update planning docs for Decision 0014 and runner library").

## Common staleness patterns

- New decision files on disk not listed in prompt decision lists or `plans/README.md` range
- New prompt files on disk not referenced in any index or other prompt
- New workstream files on disk not listed in `plans/README.md` planning set
- New libraries not in repo shape diagrams or implementation slices
- New `run.py` tasks not in capabilities lists
- Version bumps not reflected in workstream verified slices
- Resolved open areas still listed as incomplete
- workspace-history missing the current session's entry
