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
| `open-questions.md` | Unresolved questions that need thought but aren't blocking | When exploring design tradeoffs or looking for things to investigate |
| `patterns.md` | Reusable implementation patterns with code examples | When writing a new library or implementing a common pattern |
| `roadmap.md` | Milestone status and trajectory | When you need the big picture of project phases |
| `sessions/` | Session logs — what happened, what was discussed, what's unfinished | When recovering context from a recent session or checking what was tried |
| `workstreams/` | Active bodies of work (only in-progress workstreams live here) | When working on a tracked initiative |

## Rules

- **Decisions are append-only.**  Record a new decision when tradeoffs matter
  or when future agents would otherwise have to rediscover context.  Use the
  format in `decisions/README.md`.  Decisions can start as `proposed` and be
  promoted to `accepted` after review.
- **`next-up.md` is the working queue.**  Move checked-off items to Done in
  the same edit.  Keep it focused on active work.
- **Open questions are low-pressure.**  Add freely, resolve when the answer
  becomes clear.  Promote to a decision when the answer involves tradeoffs.
- **Patterns are prescriptive.**  They show *how* to implement correctly.
  Link to the decision that explains *why*.
- **Session logs are ephemeral.**  Write one when a session produces context
  that won't survive in commits alone.  Delete old entries once their content
  is absorbed elsewhere.
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
