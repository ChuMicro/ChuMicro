# Decision 0017: Shared timestamp in service contract

Status: `accepted`
Date: `2026-04-03`

## Context

In a tight `while True` loop on a microcontroller, each component calling `ticks_ms()` independently sees a slightly different timestamp.  On slow microcontrollers, this drift causes components that should fire on the same tick to disagree, and ordering becomes non-deterministic.  The correct pattern is to **capture time once per loop iteration and share that timestamp** across all components.

The existing serviceable pattern (Decision 0014) uses `service(event_sink)` — components receive the sink but no shared timestamp.  Adding `now_ms` to the service contract gives components access to a consistent clock without reading it themselves.

## Decision

### Service contract gains `now_ms`

The service contract changes from `service(event_sink)` to `service(event_sink, now_ms)`.  Components that need timing (e.g., wrapping `Heartbeat.poll(now_ms)`) use the timestamp; components that don't need it (e.g., button scanners) ignore the parameter.

### ServiceRunner captures time

`ServiceRunner.service_once()` captures `ticks_ms()` once per call and passes the resulting `now_ms` to every component.  It returns `now_ms` so user code can use it for passive checks alongside the dispatch loop.

`ServiceRunner` accepts an optional `ticks` parameter (with a `ticks_ms` method) for constructor injection.  Defaults to `chumicro_timing.ticks_ms`.

### Everything else stays

`Event`, `EventQueueSink`, `SimpleEventDispatcher`, and the overall service-drain-dispatch architecture from Decision 0014 remain unchanged.

### Heartbeat accepts `now_ms`

`Heartbeat.poll(now_ms)`, `Heartbeat.is_due(now_ms)`, and `Heartbeat.reset(now_ms)` take a required `now_ms` parameter.  Heartbeat no longer reads the clock during operation — only at construction time and via the injected `ticks_diff` for wraparound math.

## Alternatives considered

- **Optional `now_ms` parameter**: rejected because nothing has been published.  A required parameter enforces the shared-timestamp pattern by making it impossible to forget.
- **Separate `ServiceContext` wrapping ticks + sink**: adds indirection that is not needed yet.  Can be introduced later without breaking the current contract.

## Consequences

- Service contract: `service(event_sink)` → `service(event_sink, now_ms)`.
- `ServiceRunner` gains an optional `ticks` constructor parameter and `service_once()` returns `now_ms`.
- `chumicro-serviceable` depends on `chumicro-timing` (for the default tick source).
- `chumicro-timing` `Heartbeat` API changes: `poll(now_ms)`, `is_due(now_ms)`, `reset(now_ms)`.
- Decision 0014's event-based architecture is preserved, not superseded.
