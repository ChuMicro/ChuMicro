# Decision 0017: Shared-timestamp service loop

Status: `accepted`
Date: `2026-04-03`

## Context

The serviceable pattern (Decision 0014) was originally built around a deferred-callback model: components emitted events into a queue, and a dispatcher called registered handler callbacks. In practice, this was callbacks with extra steps — the queue and dispatcher added complexity without meaningful decoupling for the components that existed (just `Heartbeat`).

A more fundamental problem emerged: in a tight `while True` loop, each component calling `ticks_ms()` independently sees a slightly different timestamp. On slow microcontrollers, this drift causes heartbeats that should fire on the same tick to disagree, and ordering becomes non-deterministic. The correct pattern is to **capture time once per loop iteration and share that timestamp** across all components.

This changes the design: the service loop must own the clock. Components receive time rather than reading it themselves.

## Decision

### Heartbeat accepts `now_ms`

`Heartbeat.poll(now_ms)`, `Heartbeat.is_due(now_ms)`, and `Heartbeat.reset(now_ms)` take a required `now_ms` parameter. Heartbeat no longer reads the clock during operation — only at construction time (to initialize the starting beat) and via the injected `ticks_diff` (for wraparound math).

### ServiceRunner owns the clock

`ServiceRunner` from `chumicro-serviceable` captures `ticks_ms()` once per `tick()` call and:

1. Passes `now_ms` to each registered component's `service(now_ms)` method.
2. Returns `now_ms` so user code can check passive components (e.g., `heartbeat.poll(now)`).

### The service contract is `service(now_ms)`

Active components (future MQTT, sensors, etc.) implement a duck-typed `service(self, now_ms)` method. No base class or import required.

### Event machinery removed

`Event`, `EventQueueSink`, `SimpleEventDispatcher`, and the old `ServiceRunner(services, sink, dispatcher)` are removed. They were deferred callbacks — not meaningfully different from direct function calls. The dispatcher can return if a real use case emerges.

### Dependency direction: serviceable → timing

`ServiceRunner` defaults to importing `ticks_ms` from `chumicro_timing`. This is the correct dependency direction: the loop owns the clock, so it depends on the clock source.

### `Heartbeat.service()` removed

`Heartbeat` is a passive component — `poll()` returns a boolean, and user code decides what to do. It does not implement `service(now_ms)`. Active components that need per-tick work are a separate concept.

## Alternatives considered

- **Optional `now_ms` parameter (backward compatible)**: rejected because nothing has been published. A required parameter enforces the shared-timestamp pattern by making it impossible to forget.
- **Keep the event queue for future use**: rejected — YAGNI. The queue and dispatcher can be re-introduced when a real multi-event component exists and proves the need.
- **Make Heartbeat implement `service(now_ms)`**: rejected — `poll()` returns a boolean, which is the right interface for passive timing. `service()` is for components that do internal work per tick.

## Consequences

- `chumicro-serviceable` shrinks to `ServiceRunner` + `FakeService` testing helper.
- `chumicro-timing` `Heartbeat` API changes: `poll(now_ms)`, `is_due(now_ms)`, `reset(now_ms)`.
- Serviceable depends on timing (for `ticks_ms`).
- Decision 0014's event-based pattern is superseded by this simpler model.

