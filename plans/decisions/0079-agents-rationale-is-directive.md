# Decision 0079: Argument-stopping rationale is part of the directive

Status: `proposed`
Date: `2026-05-18`
Related: [Decision 0074](0074-drift-mechanization-as-project-policy.md)

## Context

`AGENTS.md` has a sawtooth size history: a 37 KB original (mostly AI
research-citation cruft and generic boilerplate), compacted to 23 KB at
`1402e0c1` — a *healthy* pass that stripped the cruft and correctly
relocated library-domain guidance into ADRs and the style guide — then
re-accreted to ~33 KB and compacted again to 24 KB at `7f19a109`.

`7f19a109` framed itself as "directive-only; rationale → a not-auto-loaded
`AGENTS.notes.md`". It conflated three kinds of content and cut all three
the same way: pointer citations (correctly relocatable), *argument-stopping
rationale* (relocated to a file no agent opens), and operational specifics
that are themselves the directive (cut as if they were rationale). Agents
then argued rules and took the shortcuts the missing *why* existed to
foreclose — e.g. the `__slots__` rule with its "no-op on MP/CP, flash cost"
reason removed reads as arbitrary. Reversed in `9f120743`; `AGENTS.notes.md`
deleted.

## Decision

The *why* that changes agent behavior is part of the directive, not
commentary on it, and lives inline at the point the rule is stated.

A rationale clause is **argument-stopping** — and therefore directive —
if an agent reading only the bare rule would plausibly (a) argue it,
(b) take a shortcut the rule exists to prevent, or (c) misapply it for
want of the concrete form (the abbreviation table, the worked
bad/good example). Such clauses stay inline.

`AGENTS.md` may relocate out of itself only two things: pointer
citations (`Decision NNNN`, file paths) and pure dated incident anchors
(`→ <commit>` — these belong in `git log`). It may not move
behavior-changing rationale to *any* separate location, auto-loaded or
not. The constraint is on the content's role, not on a filename: a
`NOTES.md`, an `appendix`, or a `rationale/` tree would violate it the
same way `AGENTS.notes.md` did.

A compaction pass that cannot keep a rule's argument-stopping clause
inline within budget has found that the budget is wrong, not that the
clause is optional.

## Consequences

- Re-audits and compaction passes apply the three-part test above before
  cutting any *why* clause. `audit-docs` already excludes `AGENTS.md`
  (different audience); the guard for this file is this ADR plus review
  judgement, not a lint.
- This drift class is judgement-bound prose. Per [Decision 0074](0074-drift-mechanization-as-project-policy.md)
  the lintable contracts must be mechanized, but "is this clause
  argument-stopping?" is not deterministically detectable — it sits with
  the "state the principle, not the mechanism" class of
  review-only rules.
- On acceptance, cross-link this decision from the `AGENTS.md` header
  (the principle is currently embodied there in prose without a pointer).
  Held at `proposed` pending confirmation that the inline-why budget is
  the right long-term shape rather than a reaction to one bad trim.
- Size is not the success metric. The reversal landed at 27.6 KB, larger
  than the 24 KB over-trim and smaller than the 33 KB accretion;
  "direction present" is the bar, not a byte target.
