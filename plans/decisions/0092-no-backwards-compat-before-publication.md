# Decision 0092: No backwards compatibility before first publication

Status: `accepted`
Date: `2026-07-03`
Summary: Until first publication no code preserves superseded behavior: break and migrate all consumers in one commit; tests adapt to code, never code to tests; cross-runtime shims exempt.
Related: Decision 0064 (stated this per-library), Decision 0054 (carries an alias this retires), Decision 0089/0091 (surfaces the first sweep re-shapes)

## Context

Nothing in this workspace has ever been published; it has iterated privately for months.  Yet
audits keep finding weight that exists only to preserve superseded designs: deprecated-but-working
registration shapes, backward-compat aliases (Decision 0054's `_preflight_phase_subprocess_factory`),
tolerant parsing of our own old formats, and production fallbacks whose only consumer is a test
fixture.  Each was individually defensible; collectively they are the "catering to backware
compatibility, old ways" the project owner named as a founding complaint.  Decision 0064 already
stated the principle for one library ("No backwards-compatibility shims.  Pre-1.0.  Edit
forward."); this decision makes it the workspace contract.

## Decision

Until the first external publication, the workspace carries **zero backwards-in-time
compatibility**:

1. **No code preserves superseded behavior.**  No aliases for renamed symbols, no re-export
   shims, no deprecated-but-working surfaces, no tolerant readers of our own retired formats, no
   default values chosen to mimic old behavior.  The required shape for a design change is a
   breaking change with every consumer — libraries, demos, examples, tests, docs — migrated in
   the same commit.
2. **No production code caters to tests.**  A fallback, branch, or parameter whose only consumer
   is a test or fake is test-catering; delete it and adapt the test (fakes may need to become
   more faithful instead).  Tests lock *current intended* behavior, never legacy behavior.
3. **Exempt, explicitly:** cross-*runtime* compatibility (MicroPython / CircuitPython / CPython
   divergence handling, `chumicro_compat` polyfills) — that is the product, not weight — and
   tolerance toward *external* peers (broker quirks, malformed network input), which is
   robustness.

`check-version` and `check-api` remain as change-awareness gates (they describe what changed),
not as compatibility contracts (they never block a break).

## Consequences

- A compat/test-catering sweep runs as its own audit round; known seeds: the 0054 alias, the
  runner's callable-check registration shape and dual `next_deadline` conventions (Decision
  pending in the runner API design pass — now resolved as removal), producer-side `.sock`
  unwraps made redundant by runner 0.13.0's consumer-side unwrap, and `bundle_manager`'s
  manifest-less fallback glob kept for hand-built test inputs.
- Deprecation as a state ceases to exist here: a surface is either current or deleted.
- This decision self-retires at first publication, at which point a real compatibility policy
  (SemVer, deprecation windows) must replace it.  Deferred past publication by user call
  2026-08-09: the packages published 2026-07-19, but this project is still their only
  consumer, so the retirement bar is "a real external consumer appears", not the publish
  date.  Until then the rule above stands, `PUBLISHED` stays `False` in
  `scripts/check_api.py`, and the griffe compat gate stays warn-only.  Do not flip either
  on the publication trigger alone.
