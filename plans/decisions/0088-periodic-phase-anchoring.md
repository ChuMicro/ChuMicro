# Decision 0088: Periodic task phase anchoring

Status: `accepted`
Date: `2026-06-12`
Summary: Periodic registrations accept `preserve_phase=False`; True reschedules from the previous deadline (skipping missed points, never bursting), False keeps the re-anchor-from-now default.
Related: Decision 0014 (runner pattern, shared `now_ms`), Decision 0080 (runner reactor, `next_due_ms` wait scan)

## Context

`Runner.tick` reschedules a fired periodic as `ticks_add(now_ms, period_ms)` — anchored to the tick that fired it, not to the previous deadline. Every fire therefore inherits the tick's lateness: a 1 Hz publish whose handler takes ~80 ms was measured at ~1.08 s per cycle on Pi Pico W CircuitPython (2026-05-23 bake), ~8% slow, compounding without bound. Sampling and metering tasks lose phase; rate-limiting tasks are unaffected because re-anchoring guarantees at least `period_ms` between fires.

## Decision

Periodic registrations (`Runner.add(..., period_ms=...)` and `Runner.add_periodic`) accept a keyword-only `preserve_phase: bool = False`.

- `preserve_phase=False` (default, unchanged): next deadline is `ticks_add(now_ms, period_ms)`. Fires are spaced at least `period_ms` apart — rate-limit semantics, drift accumulates with tick lateness.
- `preserve_phase=True`: next deadline advances from the previous deadline in whole periods, skipping past any missed points so it always lands strictly in the future:

  ```python
  behind = ticks_diff(now_ms, entry.next_due_ms)
  periods_missed = behind // entry.period_ms + 1
  entry.next_due_ms = ticks_add(entry.next_due_ms, periods_missed * entry.period_ms)
  ```

  Fires stay aligned to the registration's original schedule regardless of handler duration. A stall longer than one period loses the missed fires (no catch-up burst); the next fire waits for the next phase point. Constant-time, allocation-free, wrap-safe within `ticks_diff`'s ~3.1-day window like every other runner deadline.

## Consequences

- Sampling, metering, and telemetry registrations opt in with `preserve_phase=True` and hold long-run cadence; LED, UI, and throttle registrations keep the default's minimum-gap guarantee.
- `next_due_ms` remains a plain future tick either way, so Decision 0080's `wait` min-scan is unaffected.
- A `preserve_phase=True` fire can follow the previous fire by less than `period_ms` (a late fire catching back up to phase) — code that needs a guaranteed minimum gap must keep the default.

## Rejected alternatives

- **Change the default to phase-preserving.** Silently breaks the minimum-gap property existing registrations may rely on (publish throttles, debounce-ish cadences). The slip is opt-in to fix; the gap guarantee should not be opt-in to keep.
- **Catch-up bursts (reschedule `next_due_ms + period_ms` without skipping).** After a 5 s stall a 10 ms periodic fires every tick until caught up — a surprise load spike that is wrong for nearly every embedded task and right for none we have.
- **A third mode enum instead of a boolean.** Two semantics exist in practice (fixed-delay, fixed-rate-with-skip); an enum invites speculative variants.
