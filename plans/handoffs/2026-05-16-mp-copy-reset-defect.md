# Handoff 2026-05-16 — MP copy-mode soft_reset defect + skill improvements

> Written in the format this session just added to `session-handoff`
> (VERIFIED/HYPOTHESIS/ASSUMED tags, point-in-time env, riskiest
> assumption, web-verify flags).  It is the first artifact to exercise
> those directives — resume per the updated `session-resume`,
> including the "validate against ground truth" step.

## What this session was about

Resumed `2026-05-16-deploy-mode-unification-phase4` (Decision 0068
Phase 4b.2).  Grew into: root-causing two independent sweep bugs,
shipping Decisions 0070 + 0071, closing the soft_reset race, fixing
the 16 sweep residuals, an audit that found ~800 silently-dropped
class-based tests, a fragmentation feature-gate, a 4-board matrix
validation, and improving the `session-handoff`/`session-resume`
skills + an AGENTS.md web-search directive.

## What got done `[VERIFIED]`

Commit arc `debda49e..` → `8d3a4580` (all pushed):

- **Decision 0070** (host-only test marker) + **0071** (per-library
  flash soft-reset) + `clear_entrypoints()` race-close — hardware
  `[VERIFIED]` on Pi Pico W CP (193→16→0 across the arc, mem flat).
- 16 sweep residuals fixed (msgpack→`_pure`, kvstore→host-only split).
- **Zero-item collection guard** + 17 class-based files interim-marked
  `__chumicro_runtimes__=("cpython",)`; Decision 0016 amended;
  `workstreams/cross-runtime-harness-class-support.md` is the durable
  plan (harness gains class discovery → revert the 17 markers; **not**
  convert ~800 tests).
- `*_memory_fragmentation` feature-gated (Decision 0058 loud-skip on
  real MP).
- `session-handoff`/`session-resume` SKILLs + AGENTS.md "Don't
  fabricate" extended (claim-tagging, ground-truth validation,
  context-corruption hygiene, web-search-over-recall).

## What's in flight

This handoff + the skill edits + the `open-questions.md` MP-copy entry
+ the next-up pointer — committed *with* this handoff, nothing else
uncommitted.  Working tree otherwise clean.

## Riskiest assumption

That "MP mount mode is clean, so real-world MP sweep is fine" makes
the MP-copy defect low-priority.  True **only** because the sweep
defaults to RAM/mount for MP.  It is invalidated the moment anyone
runs an MP sweep with `--deploy-mode flash`, or if Decision 0071's
`is_filesystem_mode` branch is ever reached on MP copy by another
path.  Check the open-questions entry first.

## To re-research / verify next session

- **The MP copy-mode `soft_reset` defect** — full `[VERIFIED]`
  root-cause + repro + `[HYPOTHESIS]` fix shape + cheapest test are in
  `plans/open-questions.md` ("Decision 0071 per-library soft_reset
  breaks the MicroPython copy-mode sweep").  Read it there; not
  duplicated here.  Needs hardware re-verification after the fix.
- Nothing here rests on training knowledge; no `[VERIFY: web]` items.

## Dead ends (do not re-walk)

- (ii)'s root cause is **not** a memory leak and **not** "transport
  dies at scale" (the prior handoff's hypotheses) — it was
  cumulative-live `sys.modules`, fixed by 0071.  Disproved by the
  `gc.mem_free` instrumentation; don't re-hypothesize leak/FAT-churn.
- Converting the ~800 class-based tests to module-level functions is
  explicitly **rejected** (user directive) — the durable fix is
  harness class discovery.  See the workstream.
- Forcing MP into copy mode was not a mistake — it is what surfaced
  the 0071 MP-copy defect.  Keep it as the repro, not a dead end.

## How to rebuild context fast

- `plans/open-questions.md` — two live entries: the MP-copy defect
  (above) and "Should every real-device file-write path
  reset-before-run" (#1 per-file flash reset still open).
- `plans/workstreams/cross-runtime-harness-class-support.md` — the
  17-marker revert plan (one reverts to `__chumicro_host_only__`).
- Decisions 0070, 0071; Decision 0016 (amended — guard + interim
  marker rules).  `git log --oneline debda49e..8d3a4580`.
- `.scratch/m_*.log`, `.scratch/mp_*.log` are gitignored and will
  **not** survive — recreate via the repro command in the
  open-questions entry.

## Gotchas

- **Extreme-context session.**  This session made several
  verified-from-memory errors (soft_reset race overstated ×2, msgpack
  mischaracterized, cwd drift, a failed perl edit, exit-code-trusted
  ×3).  The new `session-resume` "Context-corruption hygiene" section
  exists because of this session — apply it.
- 4-board matrix `[VERIFIED]` *as of 2026-05-16 — re-probe on
  resume*: Pico W CP 417/0; Lolin S2 CP transport-validated; **Lolin
  S2 MP mount 376/0 clean**; **Pico W MP copy = the defect**.
- Preflight reported success while RED three times this session —
  read the artifact, never the exit code.
