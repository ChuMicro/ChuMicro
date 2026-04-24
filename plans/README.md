# Plans

Project knowledge base — decisions, roadmap, and active work.

**If you're a contributor** and want to know *why* something works the way it does, start with `decisions/`. Everything else here is working state for maintainers and agents.

**If you're working with an AI agent**, these docs give it the context it needs to make good choices. Agents read `decisions/` before proposing structural changes, `patterns.md` before writing library code, and `next-up.md` before picking up work.

## What's here

| File / folder | Purpose | When to read it |
|---|---|---|
| `decisions/` | Durable decision records (ADRs) — *why* the workspace has its current shape | Before proposing structural or pattern changes |
| `history.md` | Design principles, rejected approaches, build-up timeline | When you need to understand *why* something is the way it is, or to check whether an approach was already tried |
| `next-up.md` | Active work queue (Now / Next / Blocked) | When picking up work or checking priorities |
| `open-questions.md` | Unresolved questions that need thought but aren't blocking | When exploring design tradeoffs or looking for things to investigate |
| `patterns.md` | Reusable implementation patterns with code examples | When writing a new library or implementing a common pattern |
| `roadmap.md` | Milestone status and trajectory | When you need the big picture of project phases |
| `workstreams/` | Active bodies of work (only in-progress workstreams live here) | When working on a tracked initiative |

## Rules

- **Decisions are append-only.**  Record a new decision when tradeoffs matter
  or when the reasoning would otherwise have to be rediscovered.  Use the
  format in `decisions/README.md`.  Decisions can start as `proposed` and be
  promoted to `accepted` after review.
- **`next-up.md` is the working queue.**  Move checked-off items to Done in
  the same edit.  Keep it focused on active work.
- **Open questions are low-pressure.**  Add freely, resolve when the answer
  becomes clear.  Promote to a decision when the answer involves tradeoffs.
- **Patterns are prescriptive.**  They show *how* to implement correctly.
  Link to the decision that explains *why*.
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

## Where each kind of knowledge lives

`plans/` is one of four homes for the assistive knowledge an agent or human needs to work in this repo.  Each is scoped to a different audience + purpose; avoid duplicating content between them.

| Kind of knowledge | Home |
|---|---|
| **Why** the workspace has its current shape (tradeoffs, alternatives rejected) | `plans/decisions/` (ADRs) |
| **What was tried before** — rejected approaches, design principles, build-up timeline | `plans/history.md` |
| **What's next / what's active** — queue, milestones, in-flight workstreams | `plans/next-up.md`, `plans/roadmap.md`, `plans/workstreams/` |
| **What's unresolved** — open questions that aren't blocking | `plans/open-questions.md` |
| **Reusable implementation patterns** (code shape, mpremote internals, subprocess-binary resolution) | `plans/patterns.md` |
| **How to contribute as a human** — setup, workflow, per-IDE setup, PR process, release process, new library, new workbench package | [`docs/contributing/`](../docs/contributing/) |
| **How to contribute as an agent** — workspace rules, skills table, context recovery, non-negotiable rules | [`AGENTS.md`](../AGENTS.md) |
| **Agent procedural scripts** — step-by-step procedures for common tasks (commit, checkpoint, debug-test-failure, etc.) | [`.github/skills/`](../.github/skills/) |
| **Operational recovery / paste-this-command troubleshooting** when something broke | [`docs/troubleshooting/`](../docs/troubleshooting/) |
| **Project overview for consumers** — what ChuMicro is, how to install | [`README.md`](../README.md) |
| **Human entry point** | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |

**The right home depends on the shape of the content, not who's reading it:**

- Decisions + tradeoffs → `plans/decisions/`.
- Multi-step recovery for a failure mode (e.g. macOS FSKit wedge) → `docs/troubleshooting/`, with a short inline pointer from the error message.
- Reusable "how to implement X" pattern with code → `plans/patterns.md`.
- One-shot "here's what happened in this session / on this date" → `plans/history.md`.
- Forward-looking "we plan to do X" → `plans/next-up.md` or a workstream doc.
- Guidance for a contributor doing task X (add a library, open a PR, run device tests) → `docs/contributing/X.md`.

If content feels like it fits two homes, pick the audience-agnostic one and cross-link — don't duplicate.
