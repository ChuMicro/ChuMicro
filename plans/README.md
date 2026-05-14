# Plans

Project knowledge base — decisions, roadmap, and active work.

**If you're a contributor** and want to know *why* something works the way it does, start with `decisions/`. Everything else here is working state for maintainers and agents.

**If you're working with an AI agent**, these docs give it the context it needs to make good choices. Agents read `decisions/` before proposing structural changes, `patterns.md` before writing library code, and `next-up.md` before picking up work.

## What's here

| File / folder | Purpose | When to read it |
|---|---|---|
| `next-up.md` | **Single source of truth for the work queue.** `## Now` (active items) / `## Next` (backlog) / `## Out of scope` / `## Investigations` / `## Done (recent)` (last ~25 shipped items). Agent-managed. | **First, every session**, after a quick `git log -20`. |
| `decisions/` | Durable decision records (ADRs) — *why* the workspace has its current shape | Before proposing structural or pattern changes |
| `patterns.md` | Reusable implementation patterns with code examples | When writing a new library or implementing a common pattern |
| `open-questions.md` | Unresolved questions that need thought but aren't blocking | When exploring design tradeoffs or looking for things to investigate |
| `workstreams/` | Active bodies of work (only in-progress workstreams live at the top level; closed / shipped ones move to `workstreams/archive/`). Pair a `<name>.md` (the plan) with a `<name>-research.md` sibling (source-pinned facts, file:line references, URL list, alternatives surveyed) when research material would otherwise be re-derived each session. | When working on a tracked initiative |
| `workstreams/archive/` | Historical record of closed / shipped workstreams. Read-only — preserved so future contributors can trace why a decision was made or how a phase rolled out. Cross-references from active docs and ADRs point here when the relevant work has shipped. | When tracing the history of a shipped feature |

**Session warm-up (cold pickup):** `git --no-pager log --oneline -20` → `next-up.md`. That's it. The other files are deep-dive on demand.

## Rules

- **`next-up.md` is the working queue and the front door.**  Each top-level bullet ≤5 bullet markers; promote to `workstreams/<name>.md` when bigger (CHU011).  `## Done (recent)` ≤5 entries — drop the oldest when adding a new one.  Move checked-off items to Done in the same edit.  Each Done entry: subject + commit hashes + headline result + workstream pointer; aim for under ~500 chars.  Verbose detail belongs in commit messages or workstream docs.
- **Decisions are append-only.**  Record a new decision when tradeoffs matter or when the reasoning would otherwise have to be rediscovered.  Use the format in `decisions/README.md`.  Decisions can start as `proposed` and be promoted to `accepted` after review.
- **Open questions are low-pressure.**  Add freely, resolve when the answer becomes clear.  Promote to a decision when the answer involves tradeoffs.
- **Patterns are prescriptive.**  They show *how* to implement correctly.  Link to the decision that explains *why*.
- **`git log` is the journal.**  Verbose session prose lives in commit messages.  When a session produces durable signal that future sessions need, lift it into the right home (Decision / Pattern / AGENTS.md non-negotiable / inline code comment) in the same commit — don't dump it into a dated journal or a parking-lot notes file.
- **Compress before commit.**  `task-checkpoint` step 3.  If a session produced a durable lesson, lift it into the right home in the same commit as the work.
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
| **Right now** — what's in flight / what's blocking | `plans/next-up.md` `## Now` |
| **Why** the workspace has its current shape (tradeoffs, alternatives rejected) | `plans/decisions/` (ADRs) |
| **Reusable implementation patterns** (code shape, mpremote internals, subprocess-binary resolution) | `plans/patterns.md` |
| **Facts about the world** — hardware quirks, tool gotchas, runtime-specific behaviors | inline code comments next to the workaround + the originating commit message; promote to a Decision or Pattern when it earns one |
| **What was tried before** — rejected approaches with `git log <range>`; superseded designs noted inline in the relevant ADR | commit messages + `plans/decisions/` (ADR bodies edited in place when a decision changes) |
| **What's next / what's active** — queue + in-flight workstreams | `plans/next-up.md`, `plans/workstreams/` |
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
- A non-obvious fact about the world (hardware quirk, tool gotcha) discovered while writing code → an inline code comment next to the workaround + the commit message.  Promote to an ADR when "we should change how we build" or to a Pattern when it grows reusable code surface.
- One-shot "here's what happened in this session / on this date" → commit message. `git log` is the journal.
- Forward-looking "we plan to do X" → `plans/next-up.md` or a workstream doc.
- Guidance for a contributor doing task X (add a library, open a PR, run device tests) → `docs/contributing/X.md`.

If content feels like it fits two homes, pick the audience-agnostic one and cross-link — don't duplicate.

**Compression principle:** every session produces signal; the brain only stays useful if signal is compressed before it sinks under noise. `git log` holds the noise (full prose, full context). The files above hold the compressed signal. The `task-checkpoint` skill enforces the compression step.
