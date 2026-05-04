# Decision 0045: chumicro-websockets — runner-shaped client + server

Status: `accepted`
Date: `2026-05-02`
Related: [Decision 0014](0014-runner-pattern.md) (runner pattern), [Decision 0031](0031-chumicro-sockets.md) (transport substrate), [Decision 0040](0040-chumicro-requests.md) (HttpClient + factory pattern), [Decision 0041](0041-chumicro-http-server.md) (HttpServer + WS-deserves-its-own-library framing), [Decision 0042](0042-library-dependency-policy.md) (Class 1 / Class 2 dep policy + factory-helper sub-rule).

## Context

`chumicro-requests` (Decision 0040) and `chumicro-http-server` (Decision 0041) cover request/response HTTP/1.1.  Real-time apps — sensor streaming, live dashboards, push notifications, MQTT-over-WS for browser clients — need persistent bidirectional framing.  WebSockets ([RFC 6455](https://www.rfc-editor.org/rfc/rfc6455.html)) is the standard.

Decision 0041 §v1-non-goals already deferred WS from `chumicro-http-server`: *"Connection-upgrade dance + long-lived framing are big enough to deserve their own library."*  Decision 0040's `HttpClient` is request-scoped (single in-flight, `RequestHandle.done`), and a websocket session is long-lived bidirectional — a different runtime model.  Mixing either in-place would corrupt the existing API contracts.  This ADR ships the deferred library.

Two existing reference implementations were surveyed and rejected as direct vendor targets:
* **MicroPython `extmod/modwebsocket.c`** (built into ESP32 + RP2 ports): incomplete — `assert(0)` on 64-bit length, fragmented frames disabled, PING/PONG silently dropped.  Useful as a future fast-path delegate (see §10 below) but not a substitute.
* **`danni/uwebsockets`** (~314 LOC pure Python): synchronous, blocking — incompatible with [Decision 0014](0014-runner-pattern.md)'s no-block contract.

We write our own runner-shaped framing parser + encoder against `chumicro-sockets` non-blocking I/O.

## Decision

### 1. Single new library `libraries/websockets/` covering both roles

One library, two top-level public classes:

* `WebSocketClient` — connect to a `ws://` or `wss://` URL, receive frames, send frames, close gracefully.  Single-connection per client (mirrors `MQTTClient`'s "one broker per client" shape).
* `WebSocketServer` — accept inbound WS connections via a handed-in TCP/TLS listening socket from `chumicro-sockets`, dispatch per-connection events through callbacks.  Bounded `max_connections`.

**Why one library, not two:** ~80 % of the code is shared (frame parser, frame encoder, close handshake, control-frame handling, opcode/state-code constants, exception hierarchy).  Server differs from client only in (a) handshake direction (validate request → send `101`, vs. send GET → validate `101`), and (b) masking direction (clients MUST mask outbound; servers MUST NOT mask outbound, and validate the inverse).  Splitting into `chumicro-websockets-client` + `chumicro-websockets-server` would duplicate ~600 LOC of wire code with no API benefit.

### 2. Runner-shaped, per Decision 0014

Both classes satisfy `check(now_ms) -> bool` + `handle(now_ms)`.  No `async`/`await`.  No threads.  Per-tick budgets keep the LED blinking through frame I/O, opening handshakes, fragmented-message reassembly, and close handshakes.

### 3. Client API

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory
from chumicro_timing import ticks_ms

client = WebSocketClient(connection_factory=chumicro_sockets_factory(radio=wifi.radio))
client.on_open = lambda: print("open")
client.on_text = lambda text: print(f"got text: {text}")
client.on_binary = lambda data: print(f"got {len(data)} bytes")
client.on_close = lambda code, reason: print(f"closed {code} {reason}")

client.connect("ws://api.example.com/stream", timeout_ms=5000)

while client.state != WebSocketState.CLOSED:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
    if client.state == WebSocketState.OPEN and want_to_send_now:
        client.send_text("hello")
        want_to_send_now = False

# graceful shutdown:
client.close(code=1000, reason="bye")
while client.state != WebSocketState.CLOSED:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
```

### 4. Server API

```python
from chumicro_websockets import WebSocketServer
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms

def on_connection(connection):
    connection.on_text = lambda text: connection.send_text(f"echo: {text}")
    connection.on_binary = lambda data: connection.send_binary(data)
    connection.on_close = lambda code, reason: print(f"client gone: {code}")

listener = tcp_listening_socket("0.0.0.0", 8080)
server = WebSocketServer(
    listener=listener,
    on_connection=on_connection,
    max_connections=2,
    accept_path="/ws",  # optional — only accept WS upgrade on this path
)

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
```

The "share a port with chumicro-http-server" question is sidestepped: `WebSocketServer` either owns its own port or it filters by URI path on a port nothing else listens on.  Mounting WS as a route inside a `chumicro-http-server` `Server` is a v2 ask — wait for a real consumer.  v1 supports the standalone-port shape only.

### 5. State machine (both classes)

```
        ┌─────────────┐
        │ CONNECTING  │   client: DNS → TCP → TLS → handshake send + recv
        └──────┬──────┘   server: per-conn READING_REQUEST → SENDING_RESPONSE
               │
               ▼
        ┌─────────────┐
        │    OPEN     │   bidirectional framing; auto-pong on PING;
        └──────┬──────┘   optional auto-ping; oversized → close(1009)
               │
               ▼
        ┌─────────────┐
        │   CLOSING   │   sent close, waiting for peer close
        └──────┬──────┘   (close_timeout_ms watchdog)
               │
               ▼
        ┌─────────────┐
        │   CLOSED    │   socket closed; `last_close_code` / `last_error` set
        └─────────────┘
```

### 6. Per-tick budgets and policies

| Knob | Default | Why |
|------|---------|-----|
| `recv_budget_per_tick` | `1024` | Mirrors `chumicro-requests` + `chumicro-mqtt`.  A 16 KB message takes ~16 ticks to drain — LED keeps blinking. |
| `send_budget_per_tick` | `1024` | Drain TX queue cooperatively. |
| `max_message_bytes` | `16384` (16 KB) | Cap the buffered inbound message.  Decision 0015 minimum board class is 256 KB MCU RAM — 16 KB leaves headroom; oversize triggers `when_oversized`. |
| `max_tx_queue_size` | `8` | Bounded send queue.  Mirrors `chumicro-mqtt.max_tx_queue_size`. |
| `when_oversized` | `DROP_WITH_EVENT` | Same enum shape as `chumicro_mqtt.WhenOversized`.  Fires `client.on_oversized(reported_length)`; `DISCONNECT` closes with code `1009`. |
| `ping_interval_ms` | `None` | Optional auto-ping.  Off by default (most servers drive their own keep-alive). |
| `pong_timeout_ms` | `30000` | Auto-close with `1011` if no pong received within window of last ping. |
| `handshake_timeout_ms` | `10000` | Total opening-handshake budget. |
| `close_timeout_ms` | `5000` | Wait this long for peer close after we sent close before forcing TCP teardown. |

### 7. Frame coverage (RFC 6455 §5)

* **Opcodes:** continuation (`0x0`), text (`0x1`), binary (`0x2`), close (`0x8`), ping (`0x9`), pong (`0xa`).  Reserved opcodes raise `WebSocketProtocolError` and close with `1002`.
* **Length:** 7-bit, 16-bit (`126`), 64-bit (`127`).  64-bit lengths above `max_message_bytes` are rejected at the length-byte stage to avoid heap pressure.
* **Mask:** client always masks outbound; server validates client masks inbound (close `1002` on missing mask).  Server never masks outbound; client validates server doesn't mask inbound (close `1002` on present mask).
* **Fragmentation:** inbound CONT-frame chains buffered up to `max_message_bytes`.  Control frames may interleave fragmented data without disturbing the in-progress assembly.  **Outbound: send-as-single-frame only in v1** (always `FIN=1`).
* **Control frames:** ping / pong / close ≤ 125 bytes per RFC.  Auto-pong on inbound ping (within next handle tick).  Close-frame body parsed as `(2-byte code, UTF-8 reason)`.
* **UTF-8 validation on text frames** (RFC 6455 §8.1, MUST).  Invalid UTF-8 closes with `1007` (`CLOSE_BAD_DATA`).

### 8. TLS

* **`wss://` client** — reuses `chumicro_sockets.tls_client_socket` + `chumicro_sockets.ssl_context_with_ca` per Decision 0040 §"Live-board limitations".  RTC-must-be-set + CA-must-be-pinned + flash-deploy-mode-on-Pi-Pico-W constraints carry over verbatim — documented in the library guide as "see chumicro-requests TLS notes."
* **`wss://` server** — `WebSocketServer` accepts any handed-in listener including TLS ones from `chumicro_sockets.tls_listening_socket`.  Per the post-0041 sockets work (commits `5316181` + the in-flight CP-rp2 docstring follow-up), `tls_listening_socket` works on MP everywhere + CP-on-S2/S3, and refuses up-front with `UnsupportedSSLConfigError` on CP-on-rp2.  No new error class needed — the underlying transport already raises.

### 9. v1 non-goals

* **Permessage-deflate (RFC 7692).**  zlib pulls flash; mbedTLS already uses heap.  Wait for a consumer.
* **Subprotocol negotiation (`Sec-WebSocket-Protocol`).**  v1 ignores both inbound request-side and outbound response-side; the header is never sent and never validated.  Document.
* **Extension negotiation (`Sec-WebSocket-Extensions`).**  v1 advertises none, ignores any returned.
* **Outbound fragmentation.**  Always `FIN=1` for v1 sends.  Inbound fragmentation IS supported.
* **Mounting on `chumicro-http-server` router.**  Standalone port only in v1.  Sharing a port with HTTP would require the server to peek-then-route, which conflicts with `chumicro-http-server`'s request-line-first parser.
* **Per-message send-completion callback.**  Send is fire-and-forget into the bounded TX queue; `WebSocketBackpressureError` raises on overflow when `when_oversized=DISCONNECT`.  No `on_send_complete` callback in v1.
* **Auto-reconnect.**  Caller's responsibility.  `WebSocketClient` becomes `CLOSED` and stays there; create a new client to reconnect.  Mirrors `MQTTClient`.
* **Cookies / auth helpers.**  Caller adds `Cookie:` / `Authorization:` headers via `extra_headers={...}` parameter at `connect()` time.

### 10. Dependencies (per Decision 0042 Class 1)

* Hard deps in `pyproject.toml`: `chumicro-sockets`, `chumicro-timing`.
* `chumicro_websockets.sockets_factory.chumicro_sockets_factory(radio=...)` lives in **its own submodule** per the [Decision 0042 sub-rule](0042-library-dependency-policy.md) — `__init__.py` does not import it, so users injecting custom transports don't pay the deploy cost.  This is the first new library to ship under the sub-rule from day 1 (the `chumicro-requests` follow-up audit retrofits the same shape there).
* Constructor takes `connection_factory` (client) or `listener` (server) explicitly — no auto-defaulting inside the constructor.

### 11. Testing strategy

* `chumicro_websockets.testing.FakeConnection` — bidirectional in-memory pipe with `feed_inbound(bytes)` + `read_outbound() -> bytes`.  Reuses the FakeSocket pattern from `chumicro_sockets.testing`.
* Frame-level tests use raw byte arrays per RFC 6455 §5.7 sample frames + control-frame examples.
* Cross-runtime compatibility verified via `python scripts/run.py test-all-runtimes`.
* Autobahn's full test suite is too big to ship; we cover RFC 6455 §5 (framing), §7 (close), §8 (UTF-8 validation), and §10 (security / masking) by hand-written cases.
* Live-board verification (slice 6 below) connects to a host-side CPython `websockets` PyPI server.

### 12. Implementation slices

Each slice ends with green preflight (`python scripts/run.py preflight --coverage-threshold 94`) + `task-checkpoint` commit.

* **Slice 1 — `_wire.py` + frame tests.**  Constants, exception hierarchy, URL parser, opening-handshake encoder + Sec-WebSocket-Accept derivation (`sha1` + `b2a_base64`), `FrameParser` (streaming, EAGAIN, fragmentation, 64-bit length, mask validation, UTF-8 validation), `FrameEncoder` (masked + unmasked), `CaseInsensitiveDict` (inlined copy from `chumicro-requests` per the copy-don't-couple rule until the third HTTP consumer triggers `chumicro-http` extraction).  Tests cover RFC 6455 §5.7 sample frames + control-frame interleaving + fragmentation + oversize rejection + UTF-8 rejection.
* **Slice 2 — `WebSocketClient` + tests.**  State machine, `connect()` (DNS → TCP → TLS → handshake send + parse → OPEN), `send_text` / `send_binary` / `close`, callbacks, auto-pong, optional auto-ping, handshake timeout, close timeout.  `FakeConnection`-driven tests.
* **Slice 3 — `WebSocketServer` + tests.**  Accept loop, per-`Connection` state machine (READING_REQUEST → SENDING_RESPONSE → OPEN → CLOSING → CLOSED), `Connection` object with the same send / close / callback shape as `WebSocketClient`, `on_connection` user hook, `max_connections`, `accept_path` filter (responds `404` to non-matching paths).  `FakeListener`-driven tests.
* **Slice 4 — `testing.py` + integration tests.**  Public fakes (`FakeConnection`, `FakeListener`), end-to-end client↔server in-process tests proving the framing wires up.
* **Slice 5 — `__init__.py` public API + `sockets_factory.py` + `README.md` + `docs/guide.md` + `examples/`.**  Per the `new-library` skill checklist.
* **Slice 6 — Live-board verification (`functional_tests/`).**  Loopback tests against a host-CPython `websockets` PyPI package server; hardware-gated via `devices.yml` defaults.  Mirrors the `chumicro-requests` slice 3c live-board pattern.

## Consequences

* New device library `libraries/websockets/` ships pure-Python source compatible with all three runtimes.  Estimated ~1,500–2,000 LOC src + ~2,500–3,500 LOC tests; wheel ~12–18 KB.  Mirrors `chumicro-mqtt`'s shape and weight.
* The `chumicro-http-server` "WS routes" v2 ask becomes meaningfully scoped: when it lands, `WebSocketServer.Connection` factors out from the accept loop so `chumicro-http-server` can route a request into it after parsing the upgrade header.  Not v1.
* The "extract `chumicro-http` shared primitives" follow-up from Decision 0040 §Consequences and Decision 0041 §Consequences is now triggerable — `chumicro-websockets` is the third HTTP/1.1-aware consumer.  **Defer until either `chumicro-http-server` or `chumicro-requests` next needs a wire-format change**; coordinated migration is cheaper than incremental copy-merging.  v1 inlines its handshake encoder.
* Decision 0042 sub-rule (factory helper in own submodule) gets its first new application from day 1 — the `chumicro-requests` follow-up audit will retrofit the same shape.
* TLS-server v1 stance: works wherever `chumicro_sockets.tls_listening_socket` works (MP everywhere, CP-on-S2/S3); CP-on-rp2 is refused up-front by the underlying transport (no new logic in this library).
* MicroPython `extmod/modwebsocket` native delegation (analogous to `chumicro-msgpack`'s C-module fast path) is **not** wired in v1 — the MP module is too incomplete (no fragmentation, no 64-bit length, no PING/PONG handling) for the gap to be worth the dual-path complexity.  Re-evaluate when MP fixes the gaps.
