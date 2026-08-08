# Workstream: non-blocking-connect implementation

Status: **shipped.**  Implements [Decision 0081](../../decisions/0081-non-blocking-connect-via-tick-driven-connector.md).  Surfaced 2026-05-23 by the A1+A2 negative bake against the convergence-steps-1-7 fix set on Pi Pico W CP custom firmware: self-heal correctly detected broker death + reconnected, but each outage burned ~10 s of full-tick-rate ECONNRESET retries against the wifi radio, fully stalling the runner during the outage window.  Recovery worked; runner-shape was violated for ~10 s per outage.

All client-side phases shipped; A1 bake-validated on Pi Pico W CP (max_tick_ms 63 ms during outage + recovery, ~160× drop from the pre-Phase-2 ~10 s stall).  Phase 6 (server-side accept-connector analog) closed out of scope — see the Phase-6 row in the validation history for the deferral rationale.  A future bake observation can reopen it as a separate workstream.

## Problem

The synchronous-factory promise from [Decision 0031](../../decisions/0031-chumicro-sockets.md) §2 — *"`connect()` happens inside the factory — the returned socket is already connected"* — predates the runner-shaped rule from [Decision 0051](../../decisions/0051-runner-shaped-as-project-policy.md).  Every library that uses the synchronous factory (`chumicro_mqtt`, `chumicro_requests`, `chumicro_websockets`, `chumicro_http_server`) calls it from a runner-tick handler somewhere — for self-heal, for lazy-connect-on-demand, for a session-establishment step — and each such call stalls the runner for the full DNS + TCP + TLS round-trip.

[Decision 0081](../../decisions/0081-non-blocking-connect-via-tick-driven-connector.md) lays down the invariant (library network I/O doesn't block) and the carve-out (synchronous factory stays for non-runner contexts).  This workstream covers the mechanism.

## Connector contract

`chumicro-sockets` gains two new factories alongside the existing synchronous ones:

```python
tcp_client_connector(host, port, *, radio=None) -> SocketConnector
tls_client_connector(host, port, *, context=None, radio=None) -> SocketConnector
```

`SocketConnector` is a tick-driven state machine.  Each call to `connector.tick(now_ms)` advances one phase; phases that require network I/O return immediately when their underlying socket would block.  The connector exposes the runner-contract surface (`io_socket` / `io_wants_read` / `io_wants_write` / `next_deadline`) so the runner can park in `Runner.wait` until POLLIN / POLLOUT / timeout fires.

```python
class SocketConnector:
    state: str  # "awaiting_dns" | "awaiting_tcp" | "awaiting_tls" | "ready" | "failed"
    socket: TCPClientSocket | None  # Set when state == "ready"; None otherwise.
    last_error: Exception | None    # Set when state == "failed".

    # Runner-contract surface (same shape as any I/O service).
    io_socket: object | None
    io_wants_read: bool
    io_wants_write: bool

    def tick(self, now_ms: int) -> None: ...
    def next_deadline(self, now_ms: int) -> int | None: ...
    def cancel(self) -> None: ...  # Close any in-flight socket, transition to "failed".
```

The connector can be registered with `Runner.add()` directly (object-based task, `.check()` returns `True` while state is non-terminal, `.handle()` calls `.tick()`).  In practice consumers (`chumicro-mqtt`, etc.) embed the connector in their own state machine rather than registering it directly.

## Per-runtime substrate

The three runtimes diverge on what non-blocking-connect primitives are available; the connector contract papers over the divergence:

- **CPython** — stdlib `socket.connect()` on a non-blocking socket raises `BlockingIOError` (EINPROGRESS).  `select.poll(POLLOUT)` + `getsockopt(SO_ERROR)` reports completion.  TLS via `ssl.SSLContext.wrap_socket(do_handshake_on_connect=False)` + a loop calling `sock.do_handshake()` and catching `SSLWantReadError` / `SSLWantWriteError`.  **True non-blocking.**
- **MicroPython rp2 + esp32** — non-blocking `socket.connect()` raises `OSError(EINPROGRESS)`.  `select.poll(POLLOUT)` checks completion.  `MICROPY_SSL_MBEDTLS` builds do the TLS handshake inline in `ssl.wrap_socket` — most ports BLOCK on the handshake.  Where the port doesn't support non-blocking TLS handshake, the connector's `awaiting_tls` phase blocks for the handshake duration in `tick()` and the connector documents this substrate limit.
- **CircuitPython socketpool** — `Socket.connect()` is synchronous; `socketpool` does not expose a non-blocking-connect path.  The connector's `awaiting_tcp` phase blocks on CP — substrate limit, documented on the connector and in the platform-support matrix.  TLS via `ssl.SSLContext` is similarly synchronous.  Per-phase blocking on CP is the honest answer until CP exposes the primitives.

A future amendment may add non-blocking CP support if a future CircuitPython release exposes the primitives.  The connector contract is forward-compatible.

## `MQTTClient` state-machine migration

`MQTTClient` gains one new `ProtocolState` variant; existing `CONNECTING` semantics narrow:

- `DISCONNECTED → AWAITING_TRANSPORT` — `connect()` constructs the connector via the configured connector-factory and stores it.  No network I/O on the caller's thread.
- `AWAITING_TRANSPORT → CONNECTING` — `handle()` calls `connector.tick(now_ms)`; when `connector.state == "ready"`, the underlying socket moves to `self._socket`, the connector is dropped, and the MQTT CONNECT packet is queued.
- `AWAITING_TRANSPORT → FAILED` — connector reports `state == "failed"`; `last_error` carries the connector's reason.
- `CONNECTING → CONNECTED` — existing CONNACK handling, unchanged (including the SUBSCRIBE replay from commit `92dcd8fe`).
- `_attempt_self_heal` constructs a fresh connector and transitions to `AWAITING_TRANSPORT` — no separate self-heal code path; the connect state machine handles both initial and reconnect.

`connect()` returns immediately.  All I/O happens in subsequent `handle()` ticks.  Calling `connect()` from inside a runner-tick handler is safe.

## Other library migrations

Each of these currently calls the synchronous factory and must migrate to the connector form:

- **`chumicro-requests`** — `Session.request()` constructs a connector per request (or caches per-host); the connector is consumed inside the request state machine.
- **`chumicro-websockets`** — `WebSocketClient.connect()` migrates; the WS upgrade handshake is a request-shaped exchange on top of the connector.
- **`chumicro-http-server`** — server-side is `accept()`, not `connect`.  Verify whether the analogous rule applies (synchronous TLS handshake on `accept` also blocks the runner).  Possibly out of scope for this workstream; revisit.

## Implementation phases

1. **Connector foundation in `chumicro-sockets`.**  Define `SocketConnector` protocol + state machine in `chumicro_sockets/_connector.py`.  Add `tcp_client_connector` / `tls_client_connector` factories.  CPython adapter first (`_adapters/cpython.py`) — easiest substrate, fully unit-testable.  Then MP rp2 adapter, then CP socketpool adapter (with per-phase blocking documented).  Add `FakeSocketConnector` to `chumicro_sockets/testing.py` that scripts transitions deterministically.
2. **`chumicro-mqtt` migration.**  Add `AWAITING_TRANSPORT` to `ProtocolState`.  Migrate `connect()` and `_attempt_self_heal` to construct + drive a connector.  Update existing unit tests; add tests that exercise the multi-tick connect path.
3. **Bake-validate against A1 + A2.**  Expected on MP+CPython: recovery latency drops from ~10 s (current) to <1 s — the runner doesn't burn ticks on ECONNRESET retries because the connector yields between phases.  On CP: recovery latency stays roughly similar (substrate-limited) but the runner is only blocked one phase at a time instead of one long monolithic call.
4. **`chumicro-requests` migration.**  Mechanical once the connector is in.
5. **`chumicro-websockets` migration.**  Mechanical once the connector is in.
6. **`chumicro-http-server`.**  Decide whether the accept-side handshake needs a server-side analog of the connector; ADR scope may extend.

## Validation history

| Phase | Status | Commit(s) | Notes |
|---|---|---|---|
| 1.1 Connector base + CPython adapter + FakeSocketConnector | shipped | `2babeb68` | 4342 workspace tests / 95% cov / MP + CP green |
| 1.2 MicroPython rp2 adapter | shipped | `425c59fa` | Truly non-blocking TCP via EINPROGRESS + POLLOUT; TLS substrate-blocking (one-tick inline wrap_socket) |
| 1.3 CircuitPython socketpool adapter | shipped | `e1ca82fb` | Per-phase blocking is the substrate honest answer |
| 2 chumicro_mqtt migration | shipped | (this commit) | `socket_factory` → `connector_factory`, `AWAITING_TRANSPORT` state, multi-tick connect via FakeSocketConnector |
| 3 Bake-validate against A1 (broker hard-kill + restart) on Pi Pico W CP | shipped | `c42eb4b8` | Pre-Phase-2 ref: ~10 s of full-tick-rate ECONNRESET stall.  Post-Phase-2: max_tick_ms 63 ms during the 10 s window containing the outage + recovery — ~160× drop in worst-case runner-stall time.  Bake metrics: 286 sent / 286 PUBACKs / 0 in-flight leak / 0 pending leak / 0 tx_queue leak / 0 inbound gaps / heap flat across the 5-min cycle.  31 awaiting_transport → failed cycles during the broker-down window — each one yielded to the runner instead of tight-looping the wifi radio.  3 outbound publishes lost during the outage (expected with clean_session=True).  Logs: `.scratch/bake-phase3-a1-{board,mac}.log` |
| 3 Bake-validate against A1 on Pi Pico W MicroPython | shipped | (this commit) | Phase 1.2's EINPROGRESS + POLLOUT path beats CP's substrate-blocking connect: **max_tick_ms 27 ms** during the recovery window — ~2.3× better than CP's 63 ms, ~370× better than the pre-Phase-2 ~10 000 ms reference.  ~30 awaiting_transport → failed retries during the broker-down window with each yielding to the runner.  Logs: `.scratch/bake-phase3-mp-a1-{board,mac}.log` |
| 3 Bake-validate against A2 (broker graceful-disconnect of one client) on Pi Pico W MicroPython | shipped | (this commit) | A2 simulated via MQTT client-id collision (`mosquitto_pub -i bake-plain-board`) since Homebrew's mosquitto ships without the dynsec plugin compiled.  Recovery in 4 state transitions: connected → failed → awaiting_transport → connecting → connected, no retry loop (broker was up, just sent FIN).  max_tick_ms 28 ms during the recovery window.  Logs: same as MP A1. |
| 3 Bake-validate against A2 on Pi Pico W CircuitPython | shipped | (this commit) | Same client-id-collision mechanism.  Single-cycle recovery again — and because A2 doesn't trigger the ECONNRESET retry loop that bogs down CP A1, the recovery is dominated by one connect() call: **max_tick_ms 14 ms** during the recovery window.  Tells us the CP substrate-blocking cost is only load-bearing when retries fire; the steady-state and single-attempt paths are runner-shape-acceptable as-is.  Logs: `.scratch/bake-phase3-cp-a2-{board,mac}.log` |

### Phase 3 bake-validation matrix

|                 | A1 (broker hard-kill + restart) | A2 (broker graceful FIN of one client) |
|-----------------|---------------------------------|----------------------------------------|
| Pi Pico W **CP** | max_tick_ms **63 ms**           | max_tick_ms **14 ms**                  |
| Pi Pico W **MP** | max_tick_ms **27 ms**           | max_tick_ms **28 ms**                  |

Pre-Phase-2 reference (workstream's 2026-05-23 bake): ~10 000 ms tight-loop on Pi Pico W CP A1.  All four quadrants now drop into the tens-of-ms range — ~160–700× reduction depending on substrate and failure mode.  The MP-rp2 EINPROGRESS + POLLOUT path is the cleanest case; CP's substrate-blocking compromise costs ~50 ms per retry cycle but only matters when the broker is actually down (A1), not on a quick graceful disconnect (A2).
| 4 chumicro_requests migration | shipped | (this commit) | `connection_factory` → `connector_factory`, `AWAITING_TRANSPORT` state, FakeSocketConnector test idiom mirrors phase 2 |
| 5 chumicro_websockets migration | shipped | (this commit) | `connection_factory` → `connector_factory`, new `AWAITING_TRANSPORT` ConnectingPhase, FakeSocketConnector test idiom; same shape as Phase 4 |
| 6 chumicro_http_server | scope-closed | (this commit) | Server-side accept path is already non-blocking for plain HTTP (`accept()` returns EAGAIN when no client queued).  TLS handshake DOES block inline on `tls_listening_socket.accept()` (~100-500 ms per new client on Pi Pico W), but the blast radius is bounded — fires once per accepted connection, not repeatedly during outage like the connect-side ECONNRESET loop the workstream was built to fix.  An accept-side connector analog would be its own ADR + workstream when bake observation justifies the complexity (server's typical `max_connections=1` makes accept-stalls infrequent in practice).  Closed out of scope for Decision 0081. |

## What is not in scope

- **`chumicro-ntp.query`** — also performs synchronous network I/O (UDP request + reply).  Per-protocol concern; separate workstream when picked up.
- **`chumicro-wifi.connect`** — the radio-association step itself.  Different substrate (wifi chip state machine, not TCP), separate ADR.
- **Removing self-heal entirely** — rejected by Decision 0081 §Rejected.  The library owns reconnect; this workstream makes it non-blocking.
