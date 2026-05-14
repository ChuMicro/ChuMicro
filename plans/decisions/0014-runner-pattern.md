# Decision 0014: Runner pattern

Status: `accepted`
Date: `2026-04-02`
Related: Decision 0010 (testability — `CallRecorder` in `testing.py`), Decision 0042 (library dependency policy)

## Context

Multiple upcoming libraries (heartbeat, MQTT, buttons, digital I/O) will need periodic servicing and a way to communicate state changes to application code.  Without a standard contract, each library will invent its own `poll()` / callback / `next_event()` pattern, leading to inconsistent APIs and ad-hoc polling loops in user code.

On microcontrollers, each component calling `ticks_ms()` independently sees a slightly different timestamp.  On slow boards, this drift causes components that should fire on the same tick to disagree.  The correct pattern is to capture time once per loop iteration and share that timestamp across all components.

## Decision

Standardize on a **gate-based runner pattern** for all active components.

### Service contract

A service checks a condition and reports whether its handler should fire:

```python
def check(self, now_ms: int) -> bool:
    """Check one condition.

    Args:
        now_ms: Shared tick timestamp in milliseconds.

    Returns:
        True if the handler should fire.
    """
```

This is a duck-typed contract — components do not need to import or subclass anything from `chumicro-runner`.

### `now_ms` time-base contract

`now_ms` MUST be a value in `chumicro_timing.ticks_ms`'s wrapping ticks domain — modulo `2**29` milliseconds (~6.2 days), produced by the runtime's best monotonic source via the resolution chain `supervisor.ticks_ms` (CP) → `time.ticks_ms` (MP) → `time.monotonic_ns // 1_000_000` (CPython) → `int(time.monotonic() * 1000)` (final fallback).  Library implementations of runner-shaped services compute deadlines via `chumicro_timing.ticks_add` and compare elapsed time via `chumicro_timing.ticks_diff` against this base.

Any free-form monotonic value (raw `time.monotonic_ns() // 1_000_000`, `int(time.monotonic() * 1000)`, etc.) is **wrong** — even though it looks plausible.  Mixing time bases breaks `ticks_diff` because the wrap-aware signed-difference math returns nonsense when comparing a wrapping value against a non-wrapping one.  A request whose deadline computes against `chumicro_timing.ticks_ms` but is checked against `time.monotonic_ns // 1_000_000` will appear "expired" immediately on a board that has been up for more than a few seconds (the two clocks share a starting epoch on fresh boot but diverge as the non-wrapping side accumulates beyond the wrap window).

### One `ticks_ms` per tick — service-side rule

Runner-shaped services **MUST** use the supplied `now_ms` inside `check(now_ms)`, `handle(now_ms)`, and any helper reachable from them.  Never re-fetch `ticks_ms()` (or call the injected ticks object's `.ticks_ms()`) mid-tick — re-fetching produces a second timestamp microseconds later, breaking the "one shared instant per tick" guarantee that lets every service compare deadlines coherently.

The corollary: a helper that schedules a deadline must accept `now_ms` from its caller.  When the same helper is reachable from both a user-entry path (outside the tick loop, no `now_ms` available) and a `handle()` path (inside the tick loop, `now_ms` in scope), give it an optional `now_ms` kwarg that defaults to `None` — pass it from handle paths, leave it out of user-entry paths so the helper captures a fresh tick.  The two existing patterns in the codebase that follow this shape: `MQTTClient._deadline(offset_ms, *, now_ms=None)` and `_BaseSession._arm_pong_deadline(now_ms=None)`.

Fresh `ticks_ms()` is fine — and required — in user-entry methods (`connect`, `publish`, `subscribe`, etc.) that run outside any tick loop.

Drivers — application code or examples that own the `tick()` loop — pull the timestamp from one of two sources:

- `chumicro_timing.ticks_ms()` directly, when the driver's owning library declares `chumicro-timing` as a dependency.
- `helpers.ticks_ms()` (the per-library example helper that re-implements `chumicro_timing.ticks_ms`'s shape inline), when the driver is a library example that can't import `chumicro-timing` per the example dependency rule.

Both produce identical values on every supported runtime.

### Runner

`Runner(ticks=None)` captures `ticks_ms()` once per `tick()` call and passes the shared timestamp to every service.  It returns `now_ms` so user code can use it for passive checks alongside the dispatch loop.

Three registration patterns:

- **Object-based:** `add(obj)` — obj has `.check(now_ms) -> bool` and `.handle(now_ms)`.  The runner calls `.check()`; if `True`, `.handle()` is queued.
- **Callable-based:** `add(check_function, handler=function)` — callable check gates callable handler.
- **Periodic:** `add_periodic(handler, period_ms)` — handler fires on schedule, no check.

All patterns accept an optional `period_ms` to gate by time.

### Period ownership on the runner

The runner owns period gating: `add(service, period_ms=N)` creates an internal `Heartbeat` and only calls the service when the period elapses.  `TaskHandle` allows runtime mutation: `set_period()`, `remove()`.

Components that need conditional logic beyond period gating implement it in their `.check()` method.  There is one mechanism for periodic behavior, not two.

### Batch firing

`tick()` runs in two phases:

1. Check all entries (period gate → check gate) and collect due handlers.
2. Batch-fire all collected handlers.

This guarantees handlers see a consistent view of the world — no handler modifies state while other services are still being checked.

### Existing APIs remain

`Heartbeat.poll()` and `Heartbeat.is_due()` stay for simple use cases where a full runner task is unnecessary.

## Alternatives considered

- **Event-based pattern (service → event sink → dispatcher):** The initial implementation used an event bus: components emitted `Event` objects into an `EventQueueSink`, and a `SimpleEventDispatcher` routed them to handlers by event type.  This required significant ceremony (create sink, create dispatcher, register event types, pass both to runner) for simple cases where a service just needs to check a condition and fire a callback.  Removed in favor of the simpler gate-based model.  Can be re-added as a separate module when multi-handler routing is needed.
- **Priority-based dispatch ordering:** Priority constants were defined but never used for dispatch ordering.  Constants without behavior create confusion.  Deferred until the ecosystem actually needs contention management.
- **Component-owned sink / `next_event()`:** Less centralized, requires per-library queue logic, harder to orchestrate multiple components.  Rejected in favor of the runner-managed pattern.
- **`ServiceContext` wrapping ticks + sink:** Adds a layer of indirection not needed at current scale.
- **Period ownership on the dispatcher:** Created two parallel mechanisms for periodic behavior (service-side and dispatcher-side) which was confusing.  Consolidated to runner-only.

## Consequences

- `chumicro-runner` library under `libraries/runner/`.
- Service contract: `check(now_ms) -> bool` (gate-based).
- `Runner` depends on `chumicro-timing` for the default tick source and `Heartbeat` for period gating.
- `TaskHandle` provides runtime mutation of registered services.
- `CallRecorder` in the testing module records handler invocations for test assertions.
- `collections.deque` is not required by this library.
- Future libraries implementing the runner pattern use duck typing — no import dependency on `chumicro-runner` required.
