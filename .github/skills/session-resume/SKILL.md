---
name: session-resume
description: Resume work from a session handoff in plans/handoffs/. User-invoked at session start via /session-resume [<slug>] or by plain-language ask ("pick up where we left off", "resume the handoff"). Do not auto-trigger from the presence of a handoff pointer in next-up.md alone — the user may have boot intentions unrelated to the handoff.
---

# Session Resume

Pairs with [`session-handoff`](../session-handoff/SKILL.md) — write/read symmetry. The handoff skill captures session-transition context to `plans/handoffs/<date>-<slug>.md` before a session breaks; this skill enforces that the next session reads the handoff end-to-end, rebuilds any gitignored state, and confirms intent with the user before touching code.

A handoff is no use if the resuming session skips half of it and starts coding from the punch list alone.  The Gotchas, Dead ends, and To-re-research sections are the parts that prevent re-walking rejected approaches — they only pay off if the resumer actually reads them.

## When to use

Trigger conditions — all require an explicit user signal:

- `/session-resume` with no arg → latest handoff by filename date.
- `/session-resume <slug>` → specific handoff (e.g. `2026-05-12-implement-0062-factory-skip`).  Match against the slug portion of the filename; partial matches resolve to the unique full filename or fail with a list.
- User asks in plain language ("pick up where we left off", "resume the handoff", "continue the work from yesterday") — same locate-and-read flow.

## Don't use when

- The user hasn't asked to resume.  A handoff pointer in `## Now` is queue state, not a directive — the user may have boot intentions unrelated to the handoff (a quick bugfix, a question, an audit pass on something else).  Wait for the explicit signal.
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

- Migrate the `## Now` handoff-pointer entry to `## Done (recent)` as a one-line "resumed from `<YYYY-MM-DD>-<slug>` handoff" entry — verbose Done detail belongs on the punch-list bullets that pointed at the actual work, not on the pointer.  Drop the oldest `## Done (recent)` entry to stay under the 5 cap.
- **Delete the handoff file** in the same commit (`git rm plans/handoffs/<file>`).  The handoff has served its purpose; durable signal was already lifted to ADRs / `patterns.md` / commit messages / AGENTS.md by the writer; what's left in the file is session-transition scaffolding that goes stale and clutters discovery once the work lands.  Git history preserves it for anyone who wants to read it later.
- If the resume surfaced a fact worth keeping that the original handoff didn't anticipate (e.g. a wrong assumption, a discovered side-quest, a new open question, scope creep that warrants its own workstream), capture it in the appropriate canonical home **before** deleting the handoff.  The session-handoff skill's table of homes applies symmetrically here:
  - Reusable code shape → `plans/patterns.md`
  - Structural / pattern / tooling tradeoff → new ADR via `new-decision`
  - Agent-facing rule whose violation cost time → AGENTS.md
  - Hardware / runtime quirk near the workaround → inline comment + commit-message body
  - What was tried and rejected with rationale → commit message body
  - Open question waiting on user input → `plans/open-questions.md`
  - Follow-up work that's bounded and ready to pick up → new `## Next` item in `plans/next-up.md`
  - Work scope that outgrew a single next-up entry → new file under `plans/workstreams/`

  Once the handoff file is gone, anything left in it is gone too — the lift step is load-bearing.
