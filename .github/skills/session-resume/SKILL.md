---
name: session-resume
description: Resume work from a session handoff in plans/handoffs/. Auto-trigger when the top of plans/next-up.md ## Now matches the handoff-pointer shape; also user-invoked via /session-resume [<slug>] to pick up a named or latest handoff explicitly.
---

# Session Resume

Pairs with [`session-handoff`](../session-handoff/SKILL.md) — write/read symmetry. The handoff skill captures session-transition context to `plans/handoffs/<date>-<slug>.md` before a session breaks; this skill enforces that the next session reads the handoff end-to-end, rebuilds any gitignored state, and confirms intent with the user before touching code.

A handoff is no use if the resuming session skips half of it and starts coding from the punch list alone.  The Gotchas, Dead ends, and To-re-research sections are the parts that prevent re-walking rejected approaches — they only pay off if the resumer actually reads them.

## When to use

Auto-trigger conditions (read the handoff before doing anything else):

- The top entry of `plans/next-up.md` `## Now` matches the shape `**Resume <topic> from session handoff** — see [`handoffs/<file>`](handoffs/<file>)` (the shape `session-handoff` writes).

User-invoked:

- `/session-resume` with no arg → latest handoff by filename date.
- `/session-resume <slug>` → specific handoff (e.g. `2026-05-12-implement-0062-factory-skip`).  Match against the slug portion of the filename; partial matches resolve to the unique full filename or fail with a list.

## Don't use when

- `## Now` top entry is not a handoff pointer — that means the work doesn't need handoff context to resume.  Follow the entry's punch list directly via the normal session-start ritual.
- The user is asking *what's in flight* rather than *resume the work* — show them the handoff, don't auto-execute it.
- Working tree is dirty with unrelated changes — the resume sequence assumes a clean tree.  Surface the dirty state first and let the user decide.

## Steps

### 1. Locate the handoff

If invoked with a slug or partial match:

```bash
ls plans/handoffs/ | grep '<slug>'
```

If no arg, the latest by date:

```bash
ls plans/handoffs/ | grep -E '^[0-9]{4}-' | sort | tail -1
```

If the auto-trigger fired, the path is already in the `## Now` pointer — read it from there.

### 2. Read the handoff end-to-end

Every section.  Not just the punch list.  Specifically:

- `What this session was about` — the why behind the work.  Without this, the punch list is just a recipe with no context.
- `Decisions made (not yet captured in ADRs)` — anything still living in the handoff has not been ADR'd; treat it as load-bearing.
- `To re-research / verify` — work the handoff explicitly flagged as needing eyes-on before code lands.
- `Dead ends` — paths already explored.  Don't re-walk them.
- `How to rebuild context fast` — the file paths, commit SHAs, and search terms the handoff author left for you.  Read every linked file before touching code.
- `Open questions waiting on user` — blockers, not nice-to-haves.  Ask before proceeding (step 5).
- `Gotchas` — quirks and brittle assumptions.  Often the difference between landing the change cleanly and shipping a regression.

### 3. Rebuild gitignored state

Handoffs often reference state that won't survive a session boundary — typically under `.scratch/` (gitignored), occasionally env vars or board state.  The handoff's `To re-research / verify` or `How to rebuild context fast` section names what's needed and how to recreate it.  Run those steps before writing any code.

If the handoff references a fixture / probe / bench setup and doesn't include recreation steps, **stop and ask the user** — don't guess at the setup, and don't proceed without the verifying input the handoff was relying on.

### 4. Read the linked ADRs / workstreams

The handoff's `How to rebuild context fast` section points at ADRs, workstreams, key files, line numbers.  Read every linked ADR end-to-end (they're 50-150 lines); skim every linked workstream; open every file at the named line numbers and read enough surrounding context to understand the change shape.

### 5. Confirm with the user

Write one short paragraph back to the user before doing anything else:

- What the prior session was about (one sentence).
- What the next concrete step is (one sentence — the first item on the handoff's punch list).
- Anything from `Open questions waiting on user` that needs an answer first.
- Any environmental state the handoff assumed that you couldn't verify (e.g. "the handoff says `.scratch/ast-walker-check/` should have two fixture files — they're not on disk; should I recreate them with the inline command in the handoff, or did you already do that?").

Wait for the user to confirm "go" before touching code.  Resumes failed to honor this step are the most common way handoffs lose value — the resumer infers intent that the handoff author didn't actually express.

### 6. Proceed against the punch list

Once confirmed, follow the punch list from the handoff (or from `## Now`'s detail entries, if they're separate from the handoff pointer).  Apply the normal task-checkpoint discipline as units of work land.

## After the work completes

When the handoff's punch list is done:

- Migrate the `## Now` handoff-pointer entry to `## Done (recent)` as a one-line "resumed from `<YYYY-MM-DD>-<slug>` handoff" entry — verbose Done detail belongs on the punch-list bullets that pointed at the actual work, not on the pointer.
- The handoff file itself stays in git history — never delete it.  Future readers may reference it via `git log plans/handoffs/`.
- If the resume surfaced a fact worth keeping that the original handoff didn't anticipate (e.g. a wrong assumption, a discovered side-quest), capture it in the appropriate canonical home (commit message body, an ADR, `plans/patterns.md`, AGENTS.md) — don't append to the closed handoff file.
