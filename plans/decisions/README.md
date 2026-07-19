# Decisions

Use this directory for short decision records.

## Format

Each decision file should include:

- title
- status (`proposed`, `accepted`, `superseded`, or `deferred`)
- date (the date of the original decision — does not change when the body is edited)
- related decisions (by number, or "none")
- `Archived:` — optional; present only on inert records (see "Archiving dead decisions" below)
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
- **No "this decision has been revised twice" preambles.**  If you find yourself writing one, stop and edit the body instead.  <!-- noqa: CHU024 -->
- **The `Date:` field is the original decision date.**  Do not parenthesize it (`Date: 2026-04-21 (revised 2026-05-02)`).  Edits don't bump the date.
- **A correction of reasoning that was *wrong* is an in-place edit — never a new ADR.** A new superseding ADR is only for a genuine reasoning *shift* (the world changed, a real alternative is now chosen). Fixing prose that was mistaken from the start is the in-place edit, full stop. And when you do edit the old section, you do **not** also mint a standalone ADR that restates the corrected rule: one invariant lives in exactly one record. A partial-supersession that leaves the same corrected principle stated in full in *both* the edited old section and a new ADR is the bloat this rule exists to stop — pick one home, point the other at it with a bare cross-link, never a re-statement. The 0038 §3 ↔ 0075 pair was exactly this anti-pattern (and ironically the case this README's "state the principle" § teaches against), collapsed so 0075 is the invariant's only home.
- **If the change is large enough that an in-place edit would distort the original reasoning, write a new ADR that supersedes the old one** (set the old one's `Status:` to `superseded`, add `Superseded by: [Decision NNNN](…)`, and let the old body remain frozen as the historical record).  Targeted partial-supersession is also acceptable — Decision 0046 superseding §1+§7 of Decision 0029 is the worked example — but the affected sections of the older ADR get edited in place to a *bare cross-link* to the successor, not a re-statement of its rule (contrast the 0038/0075 anti-pattern above).

The four-status enum exists precisely so editors don't reach for `revised` as a hedge.  An ADR is either in force (`accepted`), replaced (`superseded`), draft (`proposed`), or set aside (`deferred`).  Edits to the body do not change which of those four it is.

## Archiving dead decisions

Session start scans this directory by `ls` — the filename *is* the
index.  A decision that no longer describes current repo state must
announce that in its filename so the index reader skips it **without
opening it**.  See [Decision 0076](0076-archive-dead-decisions-in-filename.md)
for the reasoning and the rejected alternatives (subdir move, status-only,
a fifth status).

Two dead classes, marker inserted right after the number prefix (the
`NNNN-` prefix is preserved, so cross-link and next-number recipes are
unaffected):

- **Replaced** — `Status: superseded`, a `Superseded by:` line, body
  frozen (the rule above), filename `NNNN-SUPERSEDED-BY-MMMM-<slug>.md`.
- **Spent / inert** (a one-time or bootstrap decision validly made but
  no longer load-bearing — no successor ADR) — `Status:` stays
  `accepted` (archiving is *not* a fifth status), plus an
  `Archived: inert — <one-line why>` header field and filename
  `NNNN-INERT-<slug>.md`.

When you supersede an ADR or it goes inert, rename it and fix the
inbound *filename* links (there are usually one or two; `grep -rn`
the old basename).  CHU019 enforces that status, marker, and the
`Archived:` field agree and that number prefixes stay unique — a
renamed-but-not-restatused record is a lint failure, not something a
future reader has to catch.  This is the mechanization Decision 0074
requires for a lintable contract.

## State the principle, not the mechanism

When an ADR encodes a constraint someone asked for, the decision sentence must state the **invariant**, not the implementation that prompted it.  A rule written as a mechanism-exclusion has a hole shaped like every *other* mechanism that violates the same intent — and a later contributor, reading only the written rule, builds straight through it.

The worked cautionary case: the bootstrap constraint was *"no CLI command may materialize a workspace on disk — the user clones the template repo."*  Decision 0038 recorded it as "clone, **not pip-installed scaffolder**" — the mechanism, not the principle — and its §3 explicitly rejected the stricter original ask ("retire `init`/`update`, document only the clone recipe") for convenience.  A clone-based `init` CLI then shipped: it passed the written rule (not pip) and did exactly what the spoken rule forbade (a CLI that creates the workspace).  It was removed weeks later, when intent was finally re-read against the ADR.

Practical guard: find the sentence that states the rule.  If it names a technology or implementation rather than the invariant, restate it as the invariant.  Treat any "**Rejected:** [the stricter thing actually asked for], because [convenience]" bullet as the narrowing happening in real time — that is the line to challenge before the ADR lands.  This drift class is judgement-bound prose; no lint can catch it (see [Decision 0074](0074-drift-mechanization-as-project-policy.md)), so this rule plus ADR review are the only guard.

## What does NOT belong in a decision record

ADRs capture *decision and reasoning*.  They are not living status dashboards.  When you're tempted to append any of the following to an existing ADR, route the content here instead:

- **Implementation progress / status updates** → the relevant `plans/workstreams/<name>.md` file, or the commit message of the landing commit (`git log` carries the history; `plans/next-up.md` has no `## Done` section).
- **Hardware validation logs, test reports, "N boards passed"** → commit messages on the validating commit; the ADR can name a commit hash if it needs to point at validation evidence.
- **Per-phase rollout dashboards** → `plans/workstreams/<name>.md`.
- **Future-work checklists or implementation TODO lists** → `plans/next-up.md` or `plans/open-questions.md` with a one-line pointer back from the ADR if needed.
- **Worked examples, how-to walkthroughs, contributor expectations** → `docs/contributing/<name>.md`.
- **Postmortem-style debugging writeups, shell-command recovery chains, code-block-heavy design docs** → `docs/troubleshooting/<topic>.md` or `plans/patterns.md`.

## The evidence bar for new rules

Decision records are for structural tradeoffs only.  A new lint rule or process artifact is not a structural tradeoff, and it does not earn a record on the strength of a good argument alone.  It lands only after demonstrated, shipped drift: a concrete case already in the tree where the missing rule let a mistake through.  This is the [Decision 0074](0074-drift-mechanization-as-project-policy.md) evidence bar, and it applies before the rule is written, not after.  A rule proposed to forbid a mistake nobody has made yet waits until the drift is real and pointable.
