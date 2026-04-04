# Decision 0018: Dispatcher evolution — handles, heartbeats, priorities, and time budgets

Status: `accepted` (Phases 1–2 implemented; Phases 3–4 designed for future implementation)
Date: `2026-04-03`

## Context

The Chumicro ecosystem will grow to 50+ libraries.  Many will need periodic event handlers, and the dispatch loop will need to handle contention when multiple handlers compete for limited CPU time on microcontrollers.

The current `SimpleEventDispatcher` is a minimal `{event_type: handler}` dict.  It has no concept of registration order, no way to mutate a handler after registration, and no mechanism for the dispatcher to drive periodic events itself.  Every periodic handler currently requires a full serviceable component class wrapping a `Heartbeat` — significant boilerplate for the common case.

As the ecosystem scales, the dispatcher must support: runtime mutation of handlers, periodic firing without component wrappers, ordered execution guarantees, priority levels, and time-budget enforcement to prevent slow handlers from starving the main loop.

## Decision

### Phase 1 — Handle-based registration and ordering (implemented)

`register()` returns a `HandlerHandle` — a lightweight `__slots__`-based object that provides runtime mutation:

- `handle.unregister()` — remove the handler
- `handle.set_priority(priority)` — change the priority level
- `handle.set_period(period_ms)` — add, change, or remove a heartbeat
- `handle.event_type`, `handle.priority`, `handle.period_ms`, `handle.active` — read-only properties

Internally, the dispatcher stores an ordered list of `_HandlerEntry` objects alongside a dict index for O(1) dispatch lookup.  Registration order determines execution order within equal priorities.  Re-registering the same event type replaces the old entry and moves it to the end.

The existing `unregister(event_type)` method is preserved for convenience.

### Phase 2 — Heartbeat-integrated handlers (implemented)

`register()` accepts an optional `period_ms` parameter.  When provided, the dispatcher creates a `Heartbeat` internally.  On each tick, `ServiceRunner` calls `dispatcher.poll_heartbeats(now_ms, event_sink)` which checks all heartbeat entries and emits events for any that are due.  These events flow through the normal sink → dispatch path.

This eliminates the need for a dedicated component class when all you want is a periodic callback:

```python
dispatcher.register("led.blink", lambda e: toggle_led(), period_ms=500)
```

`SimpleEventDispatcher` accepts an optional `ticks` constructor parameter for injecting a test clock.  This is passed through to internal `Heartbeat` instances.

`handle.set_period(new_ms)` replaces the heartbeat (resetting the timer).  `handle.set_period(None)` removes it.

### Phase 3 — Priority levels (designed, not yet implemented)

Four priority constants: `PRIORITY_CRITICAL` (0), `PRIORITY_HIGH` (1), `PRIORITY_NORMAL` (2), `PRIORITY_LOW` (3).  Lower number = higher priority.

`register()` accepts an optional `priority` parameter (default `PRIORITY_NORMAL`).  `handle.set_priority()` allows runtime changes.

During dispatch, events are processed in priority order.  Implementation approach: per-priority dispatch buckets (3–4 small deques) rather than sorting — O(1) insertion, O(1) drain per bucket, no allocation for sort.

Starvation prevention: track consecutive deferrals per handler entry.  After a configurable threshold (e.g., 3), temporarily promote the handler to the next tier.  Reset when the handler runs.

### Phase 4 — Time-budget enforcement (designed, not yet implemented)

`ServiceRunner` accepts an optional `budget_ms` constructor parameter.  After servicing components, a second `ticks_ms()` read establishes `dispatch_start_ms`.  Events are dispatched in priority order with elapsed-time checks after each handler.

Graduated response:

1. **Warn** — elapsed > 80% of budget → log contention (once per loop).
2. **Defer** — elapsed > budget → re-enqueue remaining low-priority events into a bounded deferral deque, replayed at the start of the next `service_once()`.
3. **Drop** — deferral buffer full after multiple rounds → drop lowest-priority events, log error.

Only `PRIORITY_LOW` events are eligible for deferral.  `PRIORITY_CRITICAL` and `PRIORITY_HIGH` always run regardless of budget.  The deferral buffer is bounded (pre-allocated deque) to prevent memory leaks.

The "capture once" principle from Decision 0017 applies to the *service phase*.  The *dispatch phase* budget checks use additional `ticks_ms()` reads which do not violate the shared-timestamp contract.

## Alternatives considered

- **Integer IDs instead of handle objects**: rejected — a handle with methods provides a cleaner API and avoids a centralized ID→entry lookup dict.
- **Priority on Event instead of handler**: rejected — keeps `Event.__slots__` unchanged (no per-event allocation increase), and deferral naturally operates on handlers.
- **Direct handler invocation for heartbeats (bypass sink)**: rejected — routing through the sink preserves the "everything goes through the sink" observability model (Decision 0014).
- **Rename SimpleEventDispatcher**: deferred — nothing published yet, rename is easy when needed.

## Consequences

- `register()` returns `HandlerHandle` (backward compatible — callers that ignored the return value are unaffected).
- `SimpleEventDispatcher.__init__` gains optional `ticks` parameter.
- `ServiceRunner.service_once()` calls `poll_heartbeats()` on the dispatcher when available.
- `chumicro-serviceable` VERSION: `0.1.0` → `0.2.0`.
- Priority constants are defined and exported but not yet used in dispatch ordering (Phase 3).
- Phases 3–4 can be implemented without breaking the Phase 1–2 API.

