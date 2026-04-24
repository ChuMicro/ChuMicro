# Decisions

Use this directory for short decision records.

## Format

Each decision file should include:

- title
- status (`proposed`, `accepted`, `superseded`, `revised`, or `deferred`)
- date
- related decisions (by number, or "none")
- context
- decision
- consequences

**Status must be one of the five values above** — no `in-progress`, no `partial`, no `shipped`.  If a decision's implementation is incomplete, it's still `accepted` (the decision was made); per-phase implementation progress lives elsewhere (see below).

Keep decisions brief. They exist to preserve reasoning, not to become design documents.

Decisions can start as `proposed` — written up for review but not yet committed to.
Promote to `accepted` once the tradeoff is confirmed.

If a decision resolves an open question from `plans/open-questions.md`, update that
file — move the question to Resolved with a one-line answer and link to the decision.

## What does NOT belong in a decision record

ADRs capture the *decision and its reasoning at a point in time*.  They are not living status dashboards.  When you're tempted to append any of the following to an existing ADR, route the content here instead:

- **Implementation progress / status updates** → `plans/history.md` (dated timeline entries) or the relevant `plans/workstreams/<name>.md` file.
- **Hardware validation logs, test reports, "N boards passed"** → `plans/history.md` under the date the validation ran.
- **Per-phase rollout dashboards** → `plans/workstreams/<name>.md`.
- **Future-work checklists or implementation TODO lists** → `plans/next-up.md` or `plans/open-questions.md` with a one-line pointer back from the ADR if needed.
- **Worked examples, how-to walkthroughs, contributor expectations** → `docs/contributing/<name>.md`.
- **Postmortem-style debugging writeups, shell-command recovery chains, code-block-heavy design docs** → `docs/troubleshooting/<topic>.md` or `plans/patterns.md`.

**Do not add dated `## Implementation status update (YYYY-MM-DD)` or `## Progress notes (YYYY-MM-DD)` sections to an ADR.**  Commit messages + `plans/history.md` already cover the "when did this ship and what changed" story.  If a decision itself has changed, either edit the decision body in place or write a new ADR that supersedes the old one (set the old one's status to `superseded` with a forward link).

When a decision's scope expands mid-flight, fold the expansion into the decision body — don't accrete `## Update (YYYY-MM-DD)` sections.  The "why it expanded" belongs in the commit message and the history timeline.
