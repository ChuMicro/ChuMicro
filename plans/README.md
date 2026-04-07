# Plans

Knowledge base for the Chumicro workspace.  Captures decisions, history, and
active work that would otherwise live in people's heads or get lost between
sessions.

## What's here

| File / folder | Purpose | When to read it |
|---|---|---|
| `decisions/` | Durable decision records (ADRs) — *why* the workspace has its current shape | Before proposing structural or pattern changes |
| `history.md` | Design principles, rejected approaches, build-up timeline | When you need to understand *why* something is the way it is, or to check whether an approach was already tried |
| `next-up.md` | Active work queue (Now / Next / Blocked) | When picking up work or checking priorities |
| `roadmap.md` | Milestone status and trajectory | When you need the big picture of project phases |
| `end-of-session.md` | Checklist for clean tree and current docs | At the end of every working session |
| `guide-generation.md` | Template for generating library `docs/guide.md` | When writing or updating a library's user guide |
| `workstreams/` | Active bodies of work (only in-progress workstreams live here) | When working on a tracked initiative |

## Rules

- **Decisions are append-only.**  Record a new decision when tradeoffs matter
  or when future agents would otherwise have to rediscover context.  Use the
  format in `decisions/README.md`.
- **`next-up.md` is the working queue.**  Move checked-off items to Done in
  the same edit.  Keep it focused on active work.
- **Don't duplicate.**  If something is already in `decisions/` or AGENTS.md,
  link to it — don't repeat it.
- **Keep history current.**  Add a timeline entry to `history.md` after
  sessions that make significant changes.

## Status vocabulary

Use these states consistently in planning documents:

- `proposed`
- `in-progress`
- `blocked`
- `done`
- `deferred`
