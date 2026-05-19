# Decision 0074: Lintable drift classes must be mechanized

Status: `accepted`
Date: `2026-05-17`
Related: [Decision 0058](0058-test-skips-must-be-loud.md), [Decision 0025](0025-dual-coverage-thresholds.md), [Decision 0079](0079-prose-drift-mechanization.md) (prose-drift consumer of this policy), the `chumicro-checks` CHU-rule family in `workbench/checks/`.

## Context

The 2026-05-16 adversarial sweep (16 agents, full tracked-file
coverage, cross-verified) produced one structural finding that
outweighs its individual defect list:

- **Every code rule mechanized by a CHU lint held at 0 violations**
  across ~16 K LOC of library source — no `typing`, no `async`, no
  relative imports, no `__slots__`, runner-shape, no long sleeps.
- **Every contract guarded only by the AGENTS.md "docs in lockstep"
  prose rule drifted and shipped wrong** — a security-relevant false
  TLS docstring, the flagship README example crashing on MicroPython, a
  "future work" docstring for fully-shipped features, 5 phantom CLI
  commands documented + 5 real ones hidden, a coverage claim the
  measurement doesn't support, and a CI lint job that can't run the CHU
  rules at all.

The split is not coincidental. Prose lockstep depends on per-change
agent diligence — the exact dependency the project mechanized *code*
rules to remove. Fixing the drifted docs without mechanizing the checks
re-arms the same failure for the next change.

## Decision

**A drift class that can be mechanically checked must be**, extending
the CHU-rule philosophy from code shape to docs / CLI / coverage / API
contracts. A contract whose violation is detectable by a deterministic
check does not get to rely on "an agent will keep the docs in lockstep"
as its only guard.

This is a *policy*, not a blanket mandate to lint everything: it
applies when (a) the contract has already drifted-and-shipped at least
once, or (b) the drift is detectable by a deterministic check without a
disproportionate maintenance burden. Genuinely judgement-bound prose
(tone, narrative, design rationale) is out of scope — it is not a
mechanizable class.

Every mechanized drift check ships with the same escape valve as the
existing CHU family: a `# noqa: CHU0NN` (`<!-- noqa: CHU0NN -->` in
Markdown) directive paired with a one-line *why* a reviewer can verify.
Mechanization removes the diligence dependency; it does not remove
human override for the legitimately-exceptional case.

## Consequences

- Implemented as **Phase 4** of the
  `audit-remediation-and-drift-mechanization` workstream: four
  `chumicro-checks` rules now ship — `CHU014`
  (doc-command-vs-registered-subcommand parity), `CHU015`
  (module-docstring capability claims vs shipped symbols), `CHU016`
  (example-script imports resolving on every declared runtime), and
  `CHU017` (coverage-claim honesty, against Decision 0025's corrected
  "what 94 % covers" contract).  Each reports zero violations on the
  current tree — the Phase 3 hand-fixes are now mechanically guarded.
- The AGENTS.md "docs in lockstep" prose rule remains, but is now a
  *backstop for the un-mechanizable remainder*, not the primary guard
  for any class a lint can own — these four classes are no longer
  diligence-dependent.
- A new drifted-and-shipped contract is, by this policy, also a
  Phase-4-class candidate — "fix the doc" is an incomplete remediation
  if the class is lintable and recurs.
- New CHU rules cost host-side CI time + maintenance, never device
  flash (`workbench/checks/` is CPython-only). The embedded-cost gate
  does not apply to this phase.
