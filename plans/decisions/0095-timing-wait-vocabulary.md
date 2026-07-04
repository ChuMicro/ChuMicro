# Decision 0095: timing owns the fleet's wait vocabulary

Status: `accepted`
Date: `2026-07-03`
Summary: `chumicro_timing` grows `Deadline`, `earliest()`, and `Rate` and hosts `Signal`; the read/write wait markers land in `chumicro_sockets.waits`; consumers stop hand-rolling deadline arithmetic.
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
2. `Signal` and `wait_for` move from `chumicro_runner` into `chumicro_timing.waits`;
   runner consumes them (dependency direction: runner → timing, already true) and keeps
   `sleep_until` (the runner owns waiting).  `wait_for` travels with `Signal` because
   leaving it behind would re-export `Signal` from runner (banned) and invert the test
   dependency floor.  The read/write I/O wait markers (`ReadWait` / `WriteWait`) land in
   `chumicro_sockets.waits`, not timing: they carry a socket, and `chumicro-sockets` takes
   no runtime dependency (bring-your-own-scheduler), so placing them in timing or runner
   would force a socket to import a scheduler it must never import.
   Decision 0091's Signal-home clause is edited in place.
3. The free functions remain the substrate; the value objects become the documented
   default surface.  Consumers migrate in the same wave (Decision 0092: break + migrate
   in one commit per library).
4. Explicitly rejected as timing's job: 64-bit monotonic emulation (defeats the
   deliberate 29-bit no-bigint design), RTC/calendar bridging (ntp's), sleep helpers
   (the runner owns waiting), scheduling (0088 keeps it in runner).

## Consequences

The vocabulary's audience is app/demo/project code and library cold paths — exactly
where both shipped raw-`+` footguns actually fired.  The library-internal per-tick
deadline scans (runner, mqtt, websockets, http_server) deliberately stay hand-rolled
int arithmetic behind their injected `ticks` seams: `earliest(*deadlines)` allocates a
varargs tuple per call and the AGENTS zero-allocation rubric protects those paths (the
greenfield study defended the same scans from objectification), and a concrete
`Deadline` import would bypass the constructor-injection seam the DI measurement showed
earning its keep.  So `earliest()` ships as the sanctioned reducer for
Deadline-holding cold paths, not a replacement for the hot scans.  The raw-`+` footgun
class becomes unwritable in code that adopts `Deadline`; timing's dependency weight
stays zero.  `Heartbeat` is deleted in favor of `Rate`.  Migration rode Wave 1 of
`plans/workstreams/core-design-realignment.md`, gated on the `sweep-devices` bake
matrix.
