# Decisions

Use this directory for short decision records.

## Format

Each decision file should include:

- title
- status (`proposed`, `accepted`, `superseded`, or `deferred`)
- date (the date of the original decision — does not change when the body is edited)
- related decisions (by number, or "none")
- context
- decision
- consequences

**Status must be one of the four values above** — no `in-progress`, no `partial`, no `shipped`, no `revised`.  If a decision's implementation is incomplete, it's still `accepted` (the decision was made).  If a decision has been edited to reflect a changed reality, it's still `accepted` (see "Edit the body in place" below).

Keep decisions brief.  They exist to preserve reasoning, not to become design documents.

Decisions can start as `proposed` — written up for review but not yet committed to.  Promote to `accepted` once the tradeoff is confirmed.

If a decision resolves an open question from `plans/open-questions.md`, delete the question from that file — the ADR (and `git log` of `open-questions.md` for context) is the durable record.

## Edit the body in place

The body of an `accepted` ADR describes the *current* state of the decision.  When the decision changes — scope expands, an alternative is rejected later, a path is renamed, a successor ADR supersedes part of it — **rewrite the affected paragraphs** so a reader landing cold gets accurate information.

This is the load-bearing rule.  It is the difference between an ADR that helps future contributors and one that misleads them.

What this means in practice:

- **No dated revision banners.**  No `Revised: YYYY-MM-DD — vocabulary update from foo to bar`.  Edit the prose to use `bar` and let `git log` carry the history.
- **No "Amended by Decision NNNN" blockquotes** at the head of a section.  If Decision NNNN superseded part of this one, edit the affected paragraph to describe the current rule and cross-link NNNN inline ("see Decision NNNN").  Do not preserve the original text "for the record" alongside a note pointing at the new state — the reader has to read both to figure out what's true.
- **No `## Amendments` / `## Update (YYYY-MM-DD)` / `## Progress notes` sections.**  Commit messages already carry the "what changed when" story; `git log <ADR-path>` shows every edit to the ADR itself.
- **No "this decision has been revised twice" preambles.**  If you find yourself writing one, stop and edit the body instead.
- **The `Date:` field is the original decision date.**  Do not parenthesize it (`Date: 2026-04-21 (revised 2026-05-02)`).  Edits don't bump the date.
- **If the change is large enough that an in-place edit would distort the original reasoning, write a new ADR that supersedes the old one** (set the old one's `Status:` to `superseded`, add `Superseded by: [Decision NNNN](…)`, and let the old body remain frozen as the historical record).  Targeted partial-supersession is also acceptable — Decision 0046 superseding §1+§7 of Decision 0029 is the worked example — but the affected sections of the older ADR still get edited in place to describe the current rule with an inline cross-link.

The four-status enum exists precisely so editors don't reach for `revised` as a hedge.  An ADR is either in force (`accepted`), replaced (`superseded`), draft (`proposed`), or set aside (`deferred`).  Edits to the body do not change which of those four it is.

## What does NOT belong in a decision record

ADRs capture *decision and reasoning*.  They are not living status dashboards.  When you're tempted to append any of the following to an existing ADR, route the content here instead:

- **Implementation progress / status updates** → the relevant `plans/workstreams/<name>.md` file (or `plans/next-up.md` `## Done (recent)` for one-line pointers).
- **Hardware validation logs, test reports, "N boards passed"** → commit messages on the validating commit; the ADR can name a commit hash if it needs to point at validation evidence.
- **Per-phase rollout dashboards** → `plans/workstreams/<name>.md`.
- **Future-work checklists or implementation TODO lists** → `plans/next-up.md` or `plans/open-questions.md` with a one-line pointer back from the ADR if needed.
- **Worked examples, how-to walkthroughs, contributor expectations** → `docs/contributing/<name>.md`.
- **Postmortem-style debugging writeups, shell-command recovery chains, code-block-heavy design docs** → `docs/troubleshooting/<topic>.md` or `plans/patterns.md`.
