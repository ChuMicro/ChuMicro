# Decision 0020: Simplify serviceable to gate-based pattern

Status: `accepted`
Date: `2026-04-04`

## Context

The serviceable library (v0.3.0) had accumulated significant complexity:

- **Event infrastructure:** `Event`, `EventQueueSink`, `SimpleEventDispatcher` — a full event bus with ring-buffered queues.
- **Handler handles:** `HandlerHandle` for dispatcher-side mutation.
- **Priority constants:** `PRIORITY_CRITICAL`, `PRIORITY_HIGH`, `PRIORITY_NORMAL`, `PRIORITY_LOW` — defined but not used in dispatch ordering.
- **Three registration paths:** gate-based (check + handler), event-based (service emits into sink, dispatcher routes), and periodic (handler on timer).

This was over-complicated for the current ecosystem size.  The event-based path required boilerplate (create sink, create dispatcher, register event types, pass both to runner) for simple cases where a service just needs to check a condition and fire a handler.  The `service(event_sink, now_ms)` contract conflated two different models:

1. A service that **decides** whether a handler fires (gate).
2. A service that **emits** typed events for a dispatcher to route (event bus).

Only the gate-based model is needed today.  The event bus can be re-added later if the ecosystem grows to need it.

## Decision

**Remove the event-based path entirely.  Simplify to gate-based + periodic.**

### Removed

- `Event`, `EventQueueSink`, `SimpleEventDispatcher`, `HandlerHandle`, `_HandlerEntry`
- `PRIORITY_CRITICAL`, `PRIORITY_HIGH`, `PRIORITY_NORMAL`, `PRIORITY_LOW`
- `FakeEventSink` from the testing module
- `event_sink` and `dispatcher` parameters on `ServiceRunner`

### Retained

- `ServiceRunner(ticks=None)` — captures time once, checks services, batch-fires handlers.
- `ServiceRunner.add(service, handler=None, period_ms=None)` — four usage patterns:
  - Object-based: `add(obj)` where obj has `.service(now_ms) -> bool` and `.handle(now_ms)`.
  - Callable-based: `add(check_fn, handler=fn)` — callable check gates callable handler.
  - Handler-only: `add(handler=fn)` — fires every tick (or per period).
  - With period: any of the above with `period_ms=N`.
- `ServiceRunner.add_periodic(handler, period_ms)` — handler fires on schedule, no check.
- `ServiceHandle` — runtime mutation: `set_period()`, `remove()`, `period_ms`, `active`.

### New

- `CallRecorder` in the testing module — a callable that records `now_ms` values for assertions.

### Service contract

The service contract changed from `service(event_sink, now_ms)` (event-based) to `service(now_ms) -> bool` (gate-based).  The check function decides IF the handler should fire.  The runner decides WHEN to check (period gating) and handles batch firing.

## Alternatives considered

- **Keep events as an advanced opt-in:** rejected — unnecessary complexity for the current ecosystem size.  Can be re-added as a separate module when multi-handler routing is needed.
- **Keep priority constants without dispatch ordering:** rejected — constants without behaviour create confusion and set expectations that don't match reality.

## Consequences

- Breaking API change: `Event`, `EventQueueSink`, `SimpleEventDispatcher`, `HandlerHandle`, priority constants removed.
- `ServiceRunner` constructor simplifies to `(ticks=None)` only.
- `FakeEventSink` replaced by `CallRecorder`.
- `chumicro-serviceable` VERSION: `0.3.0` → `0.4.0`.
- Decision 0018 Phases 1–4 are fully deferred.  The concepts (handles, priorities, time budgets) remain valid and can be re-implemented when needed.
- Decision 0019 is still valid — period ownership lives on the runner.
- `collections.deque` is no longer required by this library (was used by `EventQueueSink`).

