# Workstream: Phase 7 — first sensor thing integration log

Status: `in-progress` — sensor thing scaffolded 2026-04-26 in `things/example-sensor/` of the canonical workspace template.

## Purpose

Phase 7 is the first time every chumicro library runs together against a real broker on a real board: `chumicro-wifi` brings up the radio, `chumicro-sockets` opens a TCP/TLS connection on top, `chumicro-mqtt` does CONNECT/PUBLISH/PINGREQ traffic, `chumicro-runner` schedules the lot, `chumicro-kvstore` persists a boot counter, and `chumicro-config` reads the merged `/runtime_config.msgpack`.

Each library's own test suite exercises it in isolation — typically against a fake substrate (`FakeSocket`, `FakeWifi`, `FakeTicks`).  Phase 7 surfaces *integration* concerns that no per-library suite tests: how do services hand off state, who owns reconnection, what's the right tick order, what does a partial outage look like.

This document tracks integration issues *as they're discovered*.  Each entry is one of:

- **Open** — design decision needed; sensor thing currently has a workaround / heuristic.
- **Resolved** — design landed (in a Decision, in code, or in convention) with a forward link.
- **Deferred** — known-but-not-blocking; revisit when a real failure mode surfaces.

When an integration issue is resolved by changing a library API, the resolution flows back into the affected library's docs / tests so the next consumer doesn't rediscover it.

## Open

### `wifi`-drop while `mqtt` is connected

**Symptom:** the sensor thing's tick loop creates the MQTT socket *after* `wifi.connected == True` (early in `run()`).  If the radio later drops (deauth, AP power-cycle, signal loss), the socket the MQTT client owns silently dies — `recv_into` returns `0` or `OSError(EAGAIN)`, `send` raises, etc.  The MQTT client's state machine reacts (likely transitions to `FAILED` or `DISCONNECTED`), but the *socket itself* is now permanently dead — even after wifi reconnects, the existing socket can't be reused.

**Open question:** who owns the bringup-after-down cycle?  Three candidate shapes:

1. **MQTT client owns its bringup**: when the MQTT client transitions to `FAILED` and the underlying socket is dead, it requests a new socket from a factory and reconnects.  Requires a socket *factory* dep instead of a constructed socket.  Cleanest from the thing's perspective; mqtt is fully self-healing.
2. **Thing orchestrates**: the thing's `run()` loop watches for `mqtt.state == FAILED`, tears down the mqtt client, rebuilds the socket, rebuilds the mqtt client.  More boilerplate per thing; every thing reimplements the recovery dance.
3. **A separate "supervisor" service**: a chumicro-supplied service that watches wifi + mqtt and orchestrates re-bringup.  Adds a new abstraction; defers the question.

**Sensor thing's current shape:** none of the above — a wifi drop will leave the mqtt client in `FAILED` and publishes will quietly stop.  Acceptable for the first deploy; not acceptable for production.

**Recommendation:** shape (1).  `chumicro-mqtt`'s `MQTTClient` should optionally take a *socket factory* (`callable() -> TCPClientSocket`) in addition to the current pre-connected socket form.  When `state == FAILED` and a factory is configured, the next `handle(now_ms)` rebuilds the socket and re-issues `connect()`.  Self-healing without per-thing boilerplate.  Defer the implementation until Phase 7 actually observes the failure on hardware (don't design without data).

### Tick order when multiple services are ready

**Symptom:** when `runner.tick()` runs, every registered service's `check(now_ms)` is polled; the ones returning `True` get their `handle(now_ms)` called.  Order of handling is registration order (first-added → first-handled), per `chumicro-runner.core`.  In the sensor thing this is: `wifi`, `mqtt_client`, `publisher`.

**Concern:** `publisher.handle` calls `mqtt_client.publish` synchronously, which queues bytes on the socket.  If `mqtt_client.handle` ran *first* in this tick, the queue is drained before the publisher adds to it — fine.  If `publisher.handle` runs first (current order), the bytes sit in the queue until *next* tick when `mqtt_client.check` returns `True` again.  One-tick latency per publish.

**Open question:** is registration-order-defines-tick-order the intended contract, or is there a richer scheduler shape (priorities, dependencies, "drain after each handle")?

**Sensor thing's current shape:** publisher added last; one-tick latency on publish is fine (heartbeat is seconds-scale).  Concern only matters if a thing wants sub-tick-time round trips.

**Recommendation:** document the registration-order contract explicitly in `chumicro-runner`'s guide.  If it's truly the only contract, note that tasks that produce work for downstream tasks should be added *after* their consumer (counter-intuitive — flag prominently).  Or: reverse the contract (consumer-first) so producers get drained-from immediately.

### Service-state introspection vs callbacks

**Symptom:** the sensor thing polls `mqtt_client.state` from `HeartbeatPublisher.check` to gate publishing.  Equivalent: register an `on_connect` / `on_disconnect` callback on the mqtt client and toggle a publisher-internal `enabled` flag.  Both work.

**Open question:** which is the canonical pattern across chumicro?  `WifiService` exposes `on_state_change(callback)`; `MQTTClient` exposes `on_connect` / `on_disconnect` / `on_publish`.  Polling state via `.state` and pushing via callbacks have different reasoning patterns + failure modes.

**Recommendation:** prefer polling for *gating* work (publisher decides whether to publish *now*); prefer callbacks for *side effects* (a thing logs to disk on every disconnect, regardless of where in the loop the disconnect happened).  Document this in `chumicro-runner`'s guide.

### `runner.tick()` on a tight loop — CPU + battery

**Symptom:** the sensor thing's main loop is `while True: runner.tick()` with no sleep.  Each tick polls every service's `check`, returning quickly when no work is pending.  On a battery-powered board, this burns the CPU at 100 %.

**Open question:** does `chumicro-runner` provide a sleep-until-next-deadline primitive, or does the thing add `time.sleep_ms(...)` itself?  How does it interact with interrupt-driven wakeups (e.g. a button GPIO)?

**Sensor thing's current shape:** tight `while True: runner.tick()`.  Documented as a known issue; users on battery should add a sleep.

**Recommendation:** `chumicro-runner` should expose a `runner.next_deadline()` (lowest `next_at` across all periodic / scheduled tasks) so the thing can `time.sleep_ms(min(next_deadline_ms, 100))` between ticks.  Decision 0014's runner pattern explicitly avoids interrupts, so a 100 ms ceiling on the sleep keeps the responsiveness bound.

## Resolved

(none yet)

## Deferred

### Multi-thing sequencing

The sensor thing is a single thing.  The diff-deploy redesign captured in `plans/next-up.md` ("Replace multi-thing staging with scoped diff-deploy") is the planned answer to "what does it mean to switch between things."  Not a Phase 7 concern; revisit when a second thing exists as a fixture.

### Time-source consistency

`chumicro-mqtt` uses `chumicro-timing`'s `ticks_ms` by default.  `chumicro-wifi` uses an internal time source via `WifiConfig`.  `HeartbeatPublisher` uses `ticks_ms` directly.  All three agree today (they all wrap `chumicro-timing` in production), but a thing that injects its own time source for testing has to thread it through every service.  Worth a uniform "time source" injection pattern in `chumicro-runner` eventually; not blocking.
