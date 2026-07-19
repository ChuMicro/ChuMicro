# User Guide

## Overview

`chumicro-websockets` is a non-blocking WebSocket (RFC 6455) client + server built on `chumicro-sockets` and `chumicro-timing`.  Two top-level classes — `WebSocketClient` for outbound `ws://` / `wss://` connections, and `WebSocketServer` for inbound.  Both follow the runner pattern from `chumicro-runner` (`check(now_ms)` / `handle(now_ms)`), so an LED can keep blinking through the opening handshake, frame I/O, control-frame interleave, and the close handshake.

## Getting started with generators

The receive-stream surface reads inbound messages as a linear loop: `message = yield from client.next_message()` waits for the next message, hands it back, and loops until the session closes.  Register the client (it does the frame I/O each tick) and the consumer generator side by side.

```python
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_websockets import WebSocketClient

client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
client.connect("ws://api.example.com/stream", timeout_ms=10_000)


def receive():
    while True:
        message = yield from client.next_message()   # InboundMessage
        if message is None:
            break                                    # session closed
        print(message.text if message.is_text else message.data)


runner = Runner()
runner.add(client)
handle = runner.add_generator(receive())
runner.run_until(handle)
```

The first `next_message()` call switches inbound delivery from the `on_text` / `on_binary` callbacks to a bounded queue the generator drains (drop-oldest); pick one inbound surface per client.  See `examples/receive_stream.py`.

## Getting started with a service (client)

The `check` / `handle` service shape suits callback-style consumers and any client you drive from your own tick loop.

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_ms
from chumicro_wifi import wifi

client = WebSocketClient(
    transport_factory=connector_factory(radio=wifi.adapter.radio),
)
client.on_text = lambda text: print(f"got: {text}")
client.on_close = lambda code, reason: print(f"closed {code} {reason}")
client.connect("ws://api.example.com/stream", timeout_ms=10000)

while client.state != WebSocketState.CLOSED:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
    if client.state == WebSocketState.OPEN and want_to_send_now:
        client.send_text("hello")
        want_to_send_now = False
```

## Getting started with a service (server)

```python
from chumicro_websockets import WebSocketServer
from chumicro_sockets import listener as make_listener
from chumicro_timing import ticks_ms
from chumicro_wifi import wifi

def on_connection(connection):
    connection.on_text = lambda text: connection.send_text(f"echo: {text}")
    connection.on_close = lambda code, reason: print(f"client gone: {code}")

listener = make_listener("0.0.0.0", 8765, radio=wifi.adapter.radio)
server = WebSocketServer(
    listener=listener,
    on_connection=on_connection,
    max_connections=2,
)

while True:
    now = ticks_ms()
    if server.check(now):
        server.handle(now)
```

## Runner pattern

Both `WebSocketClient` and `WebSocketServer` implement the runner contract (`check(now_ms)` / `handle(now_ms)`) — register them with `chumicro_runner.Runner` and they get ticked alongside your other services:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(websocket_client)     # has check + handle
runner.add_periodic(led_blink, period_ms=500)
runner.add(sensor_service)

while True:
    runner.tick()
```

`check(now_ms) -> bool` reports whether work is pending; `handle(now_ms)`
does at most one tick of progress, capped by `recv_budget_per_tick` and
`send_budget_per_tick`.

## Callbacks

All callbacks default to no-op functions and fire from inside `handle()` —
never from a thread or interrupt.

### Client (`WebSocketClient`)

| Callback | Fired when |
|---|---|
| `on_open()` | The opening handshake completes; `state` is now `OPEN`. |
| `on_text(text: str)` | A complete text message has been received and UTF-8-validated. |
| `on_binary(data: bytes)` | A complete binary message has been received. |
| `on_ping(payload: bytes)` | The server sent a PING; the client has already auto-queued the PONG echo. |
| `on_pong(payload: bytes)` | The server replied to one of our PINGs. |
| `on_close(code: int, reason: str)` | The connection has reached `CLOSED` (graceful or abnormal). |
| `on_oversized(reported_length: int)` | An inbound message exceeded `max_message_bytes`; `WhenOversized` policy decided what to do. |

### Server (`Connection`)

The user wires callbacks inside `on_connection(connection)`, which fires
once per accepted connection at the moment its handshake completes:

```python
def on_connection(connection):
    connection.on_text = ...
    connection.on_binary = ...
    connection.on_close = ...
    connection.on_oversized = ...
```

Same shape as the client's callbacks; semantically identical.

## Bring your own transport

`WebSocketClient` and `WebSocketServer` don't care which library produces their sockets.  The `transport_factory` you pass to the client (and the `listener` you hand to the server) return any object matching the `SocketConnector` contract on the client side or the listener contract on the server side.  The connector advances DNS / TCP / TLS across multiple ticks; once `connector.state == "ready"`, the underlying socket must expose the four-method TCP contract:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data, returns 0 on peer-close, otherwise returns bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns bytes sent (may be partial). |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

`chumicro_sockets.connector` is one valid producer.  See `chumicro_sockets._connector.SocketConnector` for the connector contract (`tick(now_ms)`, `state`, `socket`, `io_*`, `next_deadline`, `cancel`) — any tick-driven state machine with that surface works as a custom factory.

If you supply your own factory and want `chumicro_sockets` dropped from the deploy entirely, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

Family form (`"sockets_factory"`, matches every `chumicro_*.sockets_factory`) or exact path (`"chumicro_sockets.sockets_factory"`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `WebSocketClient.from_config(...)` when `chumicro_sockets.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwarg.

For the full single-library adoption recipe — your transport, your `ticks=`, the runner-less drive loop, and host tests with no board — see [Standalone integration](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/standalone-integration.md).

## Memory notes

The library is sized for the minimum supported board class (256 KB
MCU RAM, 2 MB physical / ~800 KB usable flash):

- `max_message_bytes` defaults to `16384` (16 KB).  Inbound messages
  larger than this trigger `WhenOversized` policy.  The parser runs
  a three-tier inbound size model (mirrors `chumicro-mqtt`):
  - Tier 1, frames ≤ `payload_buffer_size` (256 B) — reuse the
    steady-state parse buffer; delivery still materializes one `bytes`
    snapshot of the payload per frame.
  - Tier 2, frames between `payload_buffer_size` and
    `max_payload_bytes` — one-shot `bytearray(payload_length)`,
    freed after delivery.
  - Tier 3, frames > `max_payload_bytes` — rolling discard, no
    allocation beyond the steady-state buffer.  The bytes are gone
    but `reported_length` is surfaced.  `WhenOversized` policy
    decides whether to stay connected (`DROP_SILENT` /
    `DROP_WITH_EVENT`, matching `chumicro-mqtt` / `chumicro-requests`)
    or close with 1009 (`DISCONNECT`).
- `max_tx_queue_size` defaults to `8` outbound messages.  Enqueueing
  past the cap raises `WebSocketBackpressureError`.  System-driven
  frames (auto-pong, close handshake) bypass the cap into 8 slots of
  headroom; a CLOSE always fits, and an auto-pong that would fill the
  last slot under a ping flood is dropped (RFC 6455 §5.5.3 allows
  answering only the most recent ping) rather than evicting a queued
  frame.
- `send_budget_per_tick` defaults to `1024` bytes.
  `recv_budget_per_tick` also defaults to `1024`.  A single `recv_into`
  fills a 512 B scratch buffer, so a tick reads the budget in 512-byte
  chunks — 1024 B/tick at the default — until the budget is spent or the
  socket has no more data; a 16 KB message takes ~16 ticks to drain
  end-to-end, well within LED-blink latency.
- The frame parser is one-shot per frame: parsed payload moves
  out of the parser into the message reassembly buffer in the
  client / connection, then the parser resets to header-reading.
  No held references to old frame bytes.

## Platform notes

| Runtime | Client (`ws://` + `wss://`) | Server (`ws://`) | Server (`wss://`) |
|---|---|---|---|
| CPython | ✅ | ✅ | ✅ |
| MicroPython | ✅ | ✅ | ✅ |
| CircuitPython on ESP32 family (S2 / S3) | ✅ | ✅ | ✅ |
| CircuitPython on Pi Pico W (rp2) | ✅ | ✅ | ❌ (raises `UnsupportedSSLConfigError`) |

### TLS (`wss://`)

`wss://` client connections reuse `chumicro_sockets.connector(tls=True)` + `chumicro_sockets.ssl_context_with_ca`, with the same live-board constraints HTTPS clients have:

- **Device RTC must be set before `wss://`.**  mbedTLS rejects every cert as "validity starts in the future" if the RTC is at boot default.  Use [`chumicro-ntp`](https://chumicro.github.io/ChuMicro/ntp/stable/) to set the clock first.
- **CA pinning is required.**  Build the `ssl_context` with `chumicro_sockets.ssl_context_with_ca(pem)` and pass it through `connector_factory(radio=..., ssl_context=ctx)`.
- **Pi Pico W needs flash deploy mode for `wss://`** — RAM-mode leaves <50 KB free for the mbedTLS handshake.

## Per-tick knobs

| Knob | Default | Why |
|---|---|---|
| `recv_budget_per_tick` | `1024` | LED-friendly inbound drain. |
| `send_budget_per_tick` | `1024` | LED-friendly outbound drain. |
| `max_message_bytes` | `16384` | 16 KB cap on assembled inbound messages. |
| `max_tx_queue_size` | `8` | Bounded TX queue. |
| `when_oversized` | `WhenOversized.DROP_WITH_EVENT` | Drop the oversized message, fire `on_oversized(reported_length)`, stay connected.  `DISCONNECT` closes with 1009 instead. |
| `ping_interval_ms` | `None` (disabled) | Optional client-side keep-alive ping cadence. |
| `pong_timeout_ms` | `30000` | Close after 30 s without PONG to a PING. |
| `handshake_timeout_ms` | `10000` | Total opening-handshake budget. |
| `close_timeout_ms` | `5000` | Wait window for peer's CLOSE before forcing TCP teardown. |

## Examples

| Example | What it shows |
|---|---|
| [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) | Wifi-capable board (CP or MP) connecting to a remote `ws://` echo server. |
| [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) | Wifi-capable board (CP or MP) accepting inbound websocket connections. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
