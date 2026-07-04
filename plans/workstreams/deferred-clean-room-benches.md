# Workstream: deferred clean-room and audit benches

> **Note (2026-07-04):** the regen-comments round-35 variance item (bench #1 below) now lives in the
> extraction repo `regen-voice-tools` (`plans/workstreams/regen-comments-variance-bench.md`); see
> `regen-voice-extraction.md`. Benches #2 and #3 stay here. This file was copied to that repo too.

Status: **parked.**  Three bench runs, each deferred 2026-06-12 on the same gate: token spend, held for
a session where the user approves the cost. They are distinct validations grouped here only by that
shared gate — un-defer any one independently when its spend is approved.

## Benches

### 1. regen-comments round-35 prompt-package variance

Variance-aware bench of the round-35 prompt package: samples, lean prompts, mode shapes, watcher recall.
Method and detail moved to the extraction repo `regen-voice-tools`
(`plans/workstreams/regen-comments-variance-bench.md`).

### 2. audit-code + audit-branch register-sample injection (n≥5)

Variance-bench the writer's register-sample injection with deterministic counts at n≥5. The injection
and the menu's per-voice preview landed 2026-06-12 at the user's call: persona-only steering read as an
impression of the author in that day's `speak_wf` A/B. This bench confirms the register gain holds
against run noise rather than resting on one lucky sample.

### 3. /audit-skill across the over-budget skills

Run `/audit-skill` against the skills that exceed the ~5k-token body budget the audit now enforces. By
the chars÷4 estimate that is audit-embedded (~11k tokens), audit-docs, audit-comments, audit-library,
regen-comments, and audit-code. audit-skill itself was rewritten under budget 2026-06-12.

## Gate

All three are deferred purely on bench-token spend (user call, 2026-06-12). None is blocked on code or
design; each runs as soon as its spend is approved, together or one at a time.

## Validation history

- 2026-06-13: filed as the shared home for three spend-gated benches previously carried as three
  separate next-up bullets.
