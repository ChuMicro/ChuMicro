# Decision 0095: timing owns the fleet's wait vocabulary

Status: `proposed`
Date: `2026-07-03`
Summary: `chumicro_timing` grows `Deadline`, `earliest()`, and `Rate`, and becomes the home of `Signal` and the read/write wait markers; consumers stop hand-rolling deadline arithmetic.
Related: 0088 (scheduler phase math), 0091 (Signal — partially superseded on acceptance), 0092, campaign reports `plans/reviews/2026-07-03-{rudiment-api-fitness,greenfield-core-redesign,consumer-driven-design-synthesis}.md`

## Context

timing ships only the dangerous free functions (`ticks_ms`/`ticks_add`/`ticks_diff`) and
makes every consumer hand-assemble the safe arm/expire/reduce pattern.  The 2026-07-03
census: that triple is re-implemented uncoordinated in seven libraries; the
earliest-of-N reduction alone is hand-rolled four times (runner, websockets,
http_server, mqtt); the raw-`+`-instead-of-`ticks_add` footgun is already tripped in two
shipped demo/bake apps.  Two independent design seats converged on the same fix shape.

## Decision

1. `chumicro_timing` gains value objects that capture the arithmetic once:
   `Deadline(period_ms)` with `expired(now_ms)`, `remaining(now_ms)`, `reset(now_ms)`;
   `earliest(*deadlines)`; `Rate` (absorbing `Heartbeat` and Decision 0088's phase math).
2. `Signal` and the read/write wait markers move from `chumicro_runner` into
   `chumicro_timing`; runner consumes them (dependency direction: runner → timing,
   already true).  Decision 0091's Signal-home clause is edited in place on acceptance.
3. The free functions remain the substrate; the value objects become the documented
   default surface.  Consumers migrate in the same wave (Decision 0092: break + migrate
   in one commit per library).
4. Explicitly rejected as timing's job: 64-bit monotonic emulation (defeats the
   deliberate 29-bit no-bigint design), RTC/calendar bridging (ntp's), sleep helpers
   (the runner owns waiting), scheduling (0088 keeps it in runner).

## Consequences

Seven private wait shapes across six files are deleted; the earliest-of reduction has
one owner; the raw-`+` footgun class becomes unwritable in code that adopts `Deadline`.
timing's dependency weight stays zero (pure arithmetic + small classes).  Migration
rides Wave 1 of `plans/workstreams/core-design-realignment.md`, gated on the
`sweep-devices` bake matrix.
