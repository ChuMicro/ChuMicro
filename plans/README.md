# Plans

Project knowledge base — decisions, roadmap, and active work.

**If you're a contributor** and want to know *why* something works the way it does, start with `decisions/`. Everything else here is working state for maintainers and agents.

**If you're working with an AI agent**, these docs give it the context it needs to make good choices. Agents read `decisions/` before proposing structural changes, `patterns.md` before writing library code, and `next-up.md` before picking up work.

## What's here

| File / folder | Purpose | When to read it |
|---|---|---|
| `now.md` | 30-second brain snapshot — current phase, in-flight, blocked, last touched. Overwritten each `task-checkpoint`. | **First, every session.** The front door. |
| `decisions/` | Durable decision records (ADRs) — *why* the workspace has its current shape | Before proposing structural or pattern changes |
| `patterns.md` | Reusable implementation patterns with code examples | When writing a new library or implementing a common pattern |
| `learnings.md` | Non-obvious facts about the world (hardware quirks, tool gotchas, classifier ordering rules). Compressed insight, not policy. | When touching a surface that has bitten before — hardware deploys, classifiers, IDE wiring |
| `history.md` | Synthesized layer: design principles, rejected approaches, build-up timeline as terse pointers into `git log` | When you need to understand *why* something is the way it is, or to check whether an approach was already tried |
| `next-up.md` | Active work queue (Now / Next / Blocked / Investigations / recent Done log) | When picking up work or checking priorities |
| `open-questions.md` | Unresolved questions that need thought but aren't blocking | When exploring design tradeoffs or looking for things to investigate |
| `roadmap.md` | Milestone status and trajectory | When you need the big picture of project phases |
| `workstreams/` | Active bodies of work (only in-progress workstreams live here; archive on completion). Pair a `<name>.md` (the plan) with a `<name>-research.md` sibling (source-pinned facts, file:line references, URL list, alternatives surveyed) when research material would otherwise be re-derived each session. Pattern from `project-workspace-research.md` (commit `4f59c0d`). | When working on a tracked initiative |

**Session warm-up (cold pickup):** read `now.md` → `git --no-pager log --oneline -20` → `next-up.md`. That's it. The other files are deep-dive on demand.

## Rules

- **`now.md` is overwritten each `task-checkpoint`.**  Five lines max.  Older snapshots recoverable from `git log plans/now.md`.
- **Decisions are append-only.**  Record a new decision when tradeoffs matter or when the reasoning would otherwise have to be rediscovered.  Use the format in `decisions/README.md`.  Decisions can start as `proposed` and be promoted to `accepted` after review.
- **`next-up.md` is the working queue.**  Move checked-off items to Done in the same edit.  Keep it focused on active work.  The `Done (recent)` section is a one-line pointer log, not a changelog — verbose detail belongs in `history.md` or workstream docs.
- **Open questions are low-pressure.**  Add freely, resolve when the answer becomes clear.  Promote to a decision when the answer involves tradeoffs.
- **Patterns are prescriptive.**  They show *how* to implement correctly.  Link to the decision that explains *why*.
- **Learnings are descriptive.**  They show *what is true about the world* (hardware, tools, runtimes).  2–6 lines per entry.  Promote to a Decision if the right response is "we should change how we build", or to a Pattern if it grows enough reusable code surface.
- **`history.md` is the synthesized layer, not a journal.**  `git log` is the journal.  Dated entries are terse pointers (1–3 lines + commit range + lifted artifacts).  If you find yourself writing prose, lift it into a Learning, Pattern, Decision, or numbered Principle / Rejected approach above.
- **Compress before commit.**  `task-checkpoint` step 3.  If a session produced a durable lesson, lift it into the right home in the same commit as the work.  Skip the dated entry entirely if the commit messages plus the lifted artifacts cover it.
- **Don't duplicate.**  If something is already in `decisions/` or AGENTS.md, link to it — don't repeat it.

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
| **Right now** — what phase / what's in flight / what's blocking | `plans/now.md` |
| **Why** the workspace has its current shape (tradeoffs, alternatives rejected) | `plans/decisions/` (ADRs) |
| **Reusable implementation patterns** (code shape, mpremote internals, subprocess-binary resolution) | `plans/patterns.md` |
| **Facts about the world** — hardware quirks, tool gotchas, classifier ordering, runtime-specific behaviors that bit us | `plans/learnings.md` |
| **What was tried before** — rejected approaches, design principles, build-up timeline | `plans/history.md` |
| **What's next / what's active** — queue, milestones, in-flight workstreams | `plans/next-up.md`, `plans/roadmap.md`, `plans/workstreams/` |
| **What's unresolved** — open questions that aren't blocking | `plans/open-questions.md` |
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
- A non-obvious fact about the world that future sessions need to know (hardware quirk, tool gotcha) → `plans/learnings.md`.
- One-shot "here's what happened in this session / on this date" → terse pointer in `plans/history.md`. The detail goes in the commit message.
- Forward-looking "we plan to do X" → `plans/next-up.md` or a workstream doc.
- Guidance for a contributor doing task X (add a library, open a PR, run device tests) → `docs/contributing/X.md`.

If content feels like it fits two homes, pick the audience-agnostic one and cross-link — don't duplicate.

**Compression principle:** every session produces signal; the brain only stays useful if signal is compressed before it sinks under noise. `git log` holds the noise (full prose, full context). The files above hold the compressed signal. The `task-checkpoint` skill enforces the compression step.
