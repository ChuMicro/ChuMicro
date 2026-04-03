# Decision 0014: Serviceable pattern

Status: `accepted`
Date: `2026-04-02`

## Context

Multiple upcoming libraries (heartbeat, MQTT, buttons, digital I/O) will need periodic servicing and a way to communicate events to application code.  Without a standard contract, each library will invent its own `poll()` / callback / `next_event()` pattern, leading to inconsistent APIs and ad-hoc drain functions in user code.

## Decision

Standardize on a **shared-sink serviceable pattern** for all active components:

1. **Event** — a small class (`source`, `event_type`, `data`) representing something that happened.
2. **EventQueueSink** — a fixed-capacity ring buffer that components emit events into.  The backing list is pre-allocated at init; individual `Event` objects are created per-emit (small, `__slots__`-based).
3. **SimpleEventDispatcher** — routes events to registered handler functions by event type.
4. **ServiceRunner** — iterates over a list of serviceable components, calls `service(event_sink)` on each, then drains and dispatches events.

### Contract for serviceable components

Any active component implements:

```python
def service(self, event_sink):
    """Do one unit of work; emit zero or more events into *event_sink*."""
```

This is a duck-typed contract — components do not need to import or subclass anything from `chumicro_serviceable`.  They just implement the method.

### Existing APIs remain

`Heartbeat.poll()` and `Heartbeat.is_due()` stay for simple use cases.  The new `service()` method is additive.

## Alternatives considered

- **Component-owned sink / `next_event()`** — less centralized, requires per-library queue logic, harder to orchestrate multiple components.  Rejected in favor of shared sink for ecosystem consistency.
- **`ServiceContext` wrapping ticks + sink** — adds a layer of indirection that is not needed yet.  Can be added later without breaking the `service(event_sink)` signature by making the context duck-type compatible with a sink.
- **Pre-allocated Event slots in the ring buffer** — avoids per-emit allocation but introduces a footgun (popped Event references become invalid on wrap).  Deferred; the user reports no GC problems in practice and this can be added as an opt-in variant later.

## Allocation notes

- `EventQueueSink` pre-allocates the backing list (fixed size, no resizing).
- `Event` uses `__slots__` to minimize per-instance memory.
- Per-emit allocation of `Event` objects is acceptable for the current scale.  If GC pressure becomes a measurable problem, a zero-allocation variant can reuse pre-allocated Event slots.

## Consequences

- New library: `chumicro-serviceable` under `libraries/serviceable/`.
- `Heartbeat` gains `service(event_sink)` and `EVENT_TICK` (minor version bump).
- Future libraries (MQTT, buttons, etc.) implement the same `service(event_sink)` contract.
- User main loops can use `ServiceRunner` for a standard dispatch pattern, or continue using `poll()` for simple cases.

