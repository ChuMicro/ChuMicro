# Decision 0019: Move period ownership from dispatcher to runner

Status: `accepted`
Date: `2026-04-03`

## Context

Decision 0018 Phase 2 added heartbeat-integrated handlers to `SimpleEventDispatcher`: `register()` accepted `period_ms`, the dispatcher created internal `Heartbeat` instances, and `ServiceRunner` called `poll_heartbeats()` each tick.  This created two parallel mechanisms for periodic behaviour:

1. **Service-side:** a component wraps a `Heartbeat` in its `service()` method and emits events when due.
2. **Dispatcher-side:** the dispatcher owns heartbeats and emits events independently of any component's `service()` call.

The dispatcher mechanism was convenient (no component class needed for simple periodic callbacks) but confusing: `period_ms` on a handler registration had no connection to service execution, and `poll_heartbeats()` was an extra step that duplicated what services already do.  The two mechanisms were unrelated despite appearing to solve the same problem.

## Decision

**Move period ownership from the dispatcher to the runner.**

### ServiceRunner gains `add()` and period gating

`ServiceRunner` no longer takes a services list in its constructor.  Services are registered via `add(service, period_ms=None)`, which returns a `ServiceHandle`.

- If `period_ms` is provided, the runner creates an internal `Heartbeat` and only calls `service()` when the period elapses.
- If `period_ms` is `None`, the service is called every tick.

`ServiceHandle` provides runtime mutation:

- `handle.set_period(new_ms)` — add, change, or remove the period.
- `handle.remove()` — remove the service from the runner.
- Read-only: `handle.period_ms`, `handle.active`.

### SimpleEventDispatcher simplifies to a pure event router

Removed from `SimpleEventDispatcher`:

- `ticks` constructor parameter
- `period_ms` parameter on `register()`
- `poll_heartbeats()` method
- `heartbeat` field on `_HandlerEntry`
- `set_period()` and `period_ms` on `HandlerHandle`

The dispatcher now does exactly one thing: route events to handlers by event type.

### One mechanism for periodic behaviour

There is now a single path for periodic services:

```python
runner = ServiceRunner(sink, dispatcher)
handle = runner.add(sensor, period_ms=5000)
handle.set_period(1000)  # change at runtime
```

Components that need conditional emission logic (e.g., only emit when a threshold is crossed) continue to use `Heartbeat` internally in their `service()` method, with no period on the runner.

## Alternatives considered

- **Keep both mechanisms:** rejected — the confusion outweighs the one-line convenience of `dispatcher.register(..., period_ms=...)`.
- **Make Heartbeat a serviceable component (add `service()` to Heartbeat):** viable but requires users to wire a Heartbeat object, add it to the services list, AND register a handler.  The `runner.add(service, period_ms=...)` API is more direct.

## Consequences

- `ServiceRunner` constructor changes: `(services, event_sink, dispatcher, ticks=None)` → `(event_sink, dispatcher, ticks=None)`.  Services added via `add()`.
- New public class: `ServiceHandle`.
- `SimpleEventDispatcher` constructor changes: `(ticks=None)` → `()`.
- `HandlerHandle` loses `set_period()` and `period_ms`.
- `chumicro-serviceable` VERSION: `0.2.0` → `0.3.0` (breaking API change).
- Decision 0018 Phase 2 is superseded by this decision.  Phases 1 (handles), 3 (priorities), and 4 (time budgets) are unaffected.

