# Prompt: End-of-session checklist

Use this prompt at the end of every working session to ensure the workspace is
clean and planning docs are current.  This checklist audits the **whole
workspace**, not just work from the current session — past sessions may have
left stale references or uncommitted changes that were never caught.

## Checklist

### 1. Run preflight

```zsh
python scripts/run.py preflight
```

Do not commit code that fails lint, tests, or build.

### 2. Check for uncommitted work

```zsh
git status --short
```

If there are uncommitted changes, stage and commit them before proceeding.

### 3. Check VERSION bumps

If any library under `libraries/` was changed (this session or in unpushed
commits from a prior session), check whether the change affects the published
surface area (new API, changed behavior, bug fix).  If so, verify the
library's `VERSION` file was bumped with the smallest correct semantic-version
increment.

### 4. Check IDE configs

If any library or support package was added or removed (now or in prior
sessions), run `python scripts/run.py sync-ide` to regenerate PyCharm and
VS Code configs.  (`new-library` calls this automatically, but manual
structural changes can leave configs stale.)

### 5. Audit planning docs for cross-doc staleness

This is the most important step.  Past sessions often leave stale references
that compound over time.  Run through this checklist even if the current
session was small.

#### 5a. Check recent commit history for unsynced changes

```zsh
git log --oneline -20
```

Scan for commits that added, removed, or renamed libraries, APIs, decisions,
or workspace structure.  For each significant change, verify that the planning
docs listed below were updated to match.

#### 5b. Scan prompt files for stale API references

For each file, verify that every code anchor, API name, class name, version
number, and decision reference matches the actual codebase:

| File | What to verify |
|---|---|
| `plans/prompts/workspace-resume.prompt.md` | Decision list complete, code anchors match actual exports, version numbers correct, open areas still open |
| `plans/prompts/workspace-rebuild.prompt.md` | Repo shape matches disk, required decisions list complete, implementation slices match actual APIs, decision descriptions match current contracts |
| `plans/prompts/workstream-planning.prompt.md` | Date stamp, decision list, code slices, version numbers, done/incomplete lists |
| `plans/prompts/workspace-history.prompt.md` | Timeline has an entry for the current session |

Specific things that go stale often:
- **Class/function names** in code anchor lists (e.g., `EventQueueSink` after
  the event system was replaced with gate-based service)
- **Version numbers** referenced in prose (e.g., "0.2.0" when it was reset to
  "0.1.0")
- **Decision descriptions** that describe a superseded contract
- **Missing new decisions or libraries** not yet added to the decision lists

#### 5c. Check planning indexes

| File | What to verify |
|---|---|
| `plans/README.md` | Decisions range covers all decision files on disk, current planning set lists all workstreams |
| `plans/next-up.md` | No checked-off items sitting in Now/Next/Blocked (should be moved to Done) |
| `plans/roadmap.md` | Milestone progress reflects actual state |

#### 5d. Run the plans-sync prompt if needed

If step 5b or 5c found issues, fix them now.  For complex drift, use the
[plans-sync prompt](./plans-sync.prompt.md) as a more thorough guide.

### 6. Commit with good messages

```zsh
git status --short
```

If there are changes from step 5, commit them.  Write commit messages that aid
context recovery — summarise *what* in the subject, explain *why* in the body
when non-trivial, and name affected libraries or decisions.  See AGENTS.md
§ Contributing and `.github/instructions/git-commit.instructions.md` for
commit mechanics.

### 7. Verify clean tree

```zsh
git status --short
```

Should produce no output.

## Quick-check shortcut for small sessions

If the session only touched one file or made a minor edit, steps 5a–5c can
be abbreviated to: "Did I change any API, add a decision, add a library, or
bump a version?  If no, skip the full scan."  But **at least skim the code
anchors** in `workspace-resume.prompt.md` and `workspace-rebuild.prompt.md`
— they are the most common source of accumulated staleness.

## Why this exists

Agent sessions can end abruptly (context window limits, timeouts, user closing
the session).  Uncommitted work is invisible to the next session.  Stale
planning docs mislead the next agent.

The end-of-session prompt previously checked only the current session's work.
But staleness accumulates across sessions — a session that renames an API may
not update all prompt files, and subsequent sessions inherit the drift.  This
expanded checklist catches both same-session and cross-session staleness.
