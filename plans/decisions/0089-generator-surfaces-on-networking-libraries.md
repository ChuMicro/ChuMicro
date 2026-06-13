# Decision 0089: Generator surfaces on the networking libraries

Status: `accepted`
Date: `2026-06-13`
Summary: `yield from` gets a public surface in two flavors: one-shot fetch in `chumicro_requests`, receive-stream `next_message` in `chumicro_websockets`; MQTT stays callbacks.
Related: Decision 0087 (generator substrate), Decision 0080 (runner reactor), Decision 0081 (non-blocking connect)

## Context

Decision 0087 built the generator substrate (`runner.add_generator`, duck-typed `io_*` waits, the `chumicro_sockets.generators` helpers) but deferred giving the reactive networking libraries their own generator surfaces — "no migration mandated." The networking demos, MQTT's especially, then read as callback cascades (each operation's completion callback triggering the next), which advertised the wrong pattern. This decision settles where a `yield from` public surface earns its place and where callbacks stay.

## Decision

**The invariant.** `yield from` is for **sequential awaits** — awaiting one operation's result, or awaiting the next item from an ongoing stream. Reactive fan-out — callbacks set once, operations queued fire-and-forget — stays callbacks. Do not wrap a fire-and-forget operation, or an ack/confirmation a caller never blocks on, in a generator.

Two flavors get a public generator surface:

1. **One-shot wait** — `chumicro_requests.generators.fetch` (plus `get` / `post` / `put` / `patch` / `delete`): `response = yield from fetch(connector_factory, url)`. The whole request lifecycle runs under `Runner.add_generator`; the caller gets the `Response` back from the `yield from` instead of polling a handle or wiring `on_done`. Reuses the I/O-free wire parser.

2. **Receive stream** — `chumicro_websockets` `WebSocketClient.next_message()` / `Connection.next_message()`: `message = yield from ws.next_message()` in a wait-process-wait loop. Backed by a bounded inbound queue (`max_inbound_queue_size`, drop-oldest); returns an `InboundMessage` while one is queued, `None` once the session is closed. The session is registered with the runner alongside the receive generator: the session does the frame I/O each tick, the generator drains.

**Reactive setup stays callbacks.** MQTT gets **no** generator API: `connect` stays an `on_connect` callback, `publish` / `subscribe` stay fire-and-forget queueing (QoS acking is internal bookkeeping the caller never blocks on), inbound stays `on_message`. Its callback cascade is a demo-cadence problem, fixed by setting callbacks once and doing setup in one `on_connect` — not by adding generators. `chumicro_http_server` is out of scope: route decorators are the idiomatic server shape; only streaming response bodies would use generators, alongside the deferred Decision 0081 Phase 6 TLS-accept work.

## Consequences

- New public surface: `chumicro_requests.generators` (opt-in submodule), and `next_message()` + `InboundMessage` + the `max_inbound_queue_size` knob on `chumicro_websockets`. Both reuse the existing connector-factory injection; neither replaces the `check`/`handle` client, which remains for repeated requests / callback delivery.
- `chumicro_runner._GeneratorWrapper.check()` is generalized: a socket-driven wait that also carries `next_deadline` (a socket read with a timeout) now resumes every tick on readiness rather than being gated until the deadline, so ready bytes are not stalled. Socket-only and sleep-only waits are unchanged.
- Decision 0087's consequence that reactive libraries keep `check`/`handle` "with no migration mandated" is edited in place to point here for which libraries gained a generator *surface* (requests, websockets) and which stay purely reactive (MQTT, http_server, wifi).
- VERSION minor bumps: `chumicro_requests` (new `generators` submodule), `chumicro_websockets` (new `next_message` surface).

## Rejected

- **An MQTT session-of-operations generator** (`yield from mqtt.connected()`, `yield from mqtt.publish_acked(...)`). QoS acking is internal bookkeeping a caller should not block on, and `connect` is a one-time setup better served by an `on_connect` callback. The easy-to-read MQTT is the paho / Adafruit-MiniMQTT shape — callbacks set once, a pumped runner loop — which the demo rewrite delivers without any new API.
- **Generator surfaces on `chumicro_http_server`.** They do not address the callback-cascade problem (route handlers are not a cascade) and only buy streaming response bodies, a separate future capability.
- **`async` / `await`.** Already rejected in Decision 0087; the generator substrate is the cooperative-scheduling primitive this builds on.
