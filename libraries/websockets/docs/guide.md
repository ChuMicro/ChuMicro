# User Guide

## Overview

`chumicro-websockets` is a non-blocking WebSocket (RFC 6455) client + server
built on `chumicro-sockets` and `chumicro-timing`.  Two top-level classes —
`WebSocketClient` for outbound `ws://` / `wss://` connections, and
`WebSocketServer` for inbound — both runner-shaped: each exposes
`check(now_ms)` / `handle(now_ms)` so an LED can keep blinking through
the opening handshake, frame I/O, control-frame interleave, and the close
handshake.

Single library, two roles — ~80% of the wire code (frame parser,
state machine, masking, handshake) is shared between client and
server, so a split into separate publishable libraries would
duplicate more than it would clarify.

## Getting started — client

```python
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory
from chumicro_timing import ticks_ms
from chumicro_wifi import wifi

client = WebSocketClient(
    connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio),
)
client.on_text = lambda text: print(f"got: {text}")
client.on_close = lambda code, reason: print(f"closed {code} {reason}")
client.connect("ws://api.example.com/stream", timeout_ms=10000)

while client.state != WebSocketState.CLOSED:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
    if client.state == WebSocketState.OPEN and want_to_send_now:
        client.send_text("hello")
        want_to_send_now = False
```

## Getting started — server

```python
from chumicro_websockets import WebSocketServer
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms
from chumicro_wifi import wifi

def on_connection(connection):
    connection.on_text = lambda text: connection.send_text(f"echo: {text}")
    connection.on_close = lambda code, reason: print(f"client gone: {code}")

listener = tcp_listening_socket("0.0.0.0", 8765, radio=wifi.adapter.radio)
server = WebSocketServer(
    listener=listener,
    on_connection=on_connection,
    max_connections=2,
)

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
```

## Runner pattern

Both `WebSocketClient` and `WebSocketServer` satisfy the
chumicro tick-runner contract (`check(now_ms)` / `handle(now_ms)`) —
drop them into a `chumicro_runner.Runner` and they get
ticked alongside your other tasks:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add_task("websocket", websocket_client)   # has check + handle
runner.add_task("led", led_blink)
runner.add_task("sensor", sensor_loop)
runner.run()
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

## Memory notes

The library is sized for the minimum supported board class (256 KB
MCU RAM, 4 MB flash):

- `max_message_bytes` defaults to `16384` (16 KB).  Inbound messages
  larger than this trigger `WhenOversized` policy.  Per-frame
  `FrameParser.max_payload_bytes` defaults to the same value, so a
  hostile peer with a 64-bit length header can't pin heap before
  the parser rejects.
- `max_tx_queue_size` defaults to `8` outbound messages.  Enqueueing
  past the cap raises `WebSocketBackpressureError`.  System-driven
  frames (auto-pong, close handshake) bypass the cap via 8 slots
  of headroom.
- `recv_budget_per_tick` / `send_budget_per_tick` default to `1024`
  bytes each.  A 16 KB message takes ~16 ticks to drain end-to-end —
  well within LED-blink latency.
- The frame parser is one-shot per frame: parsed payload moves
  out of the parser into the message reassembly buffer in the
  client / connection, then the parser resets to header-reading.
  No held references to old frame bytes.

## TLS (`wss://`)

`wss://` client connections reuse `chumicro_sockets.tls_client_socket` +
`chumicro_sockets.ssl_context_with_ca`, with the same live-board
constraints `chumicro-requests` documents for HTTPS:

- **Device RTC must be set before `wss://`.**  mbedTLS rejects every
  cert as "validity starts in the future" if the RTC is at boot
  default.  NTP-sync via `chumicro-ntp` first.
- **CA pinning is required.**  Build the `ssl_context` with
  `chumicro_sockets.ssl_context_with_ca(pem)` and pass it through
  `chumicro_sockets_factory(radio=..., ssl_context=ctx)`.
- **Pi Pico W needs flash deploy mode** for any `wss://` use —
  RAM-mode leaves <50 KB free for the mbedTLS handshake.

`wss://` **server** connections inherit
`chumicro_sockets.tls_listening_socket`'s reality: works on
MicroPython everywhere, works on CircuitPython on the ESP32 family
(S2 / S3), refused up-front by `UnsupportedSSLConfigError` on
CircuitPython on the Pi Pico W (rp2 port).

## Per-tick knobs

| Knob | Default | Why |
|---|---|---|
| `recv_budget_per_tick` | `1024` | LED-friendly inbound drain. |
| `send_budget_per_tick` | `1024` | LED-friendly outbound drain. |
| `max_message_bytes` | `16384` | 16 KB cap on assembled inbound messages. |
| `max_tx_queue_size` | `8` | Bounded TX queue. |
| `when_oversized` | `WhenOversized.DROP_WITH_EVENT` | Fire `on_oversized`, close with 1009. |
| `ping_interval_ms` | `None` (disabled) | Optional client-side keep-alive ping cadence. |
| `pong_timeout_ms` | `30000` | Close after 30 s without PONG to a PING. |
| `handshake_timeout_ms` | `10000` | Total opening-handshake budget. |
| `close_timeout_ms` | `5000` | Wait window for peer's CLOSE before forcing TCP teardown. |

## Examples

| Example | What it shows |
|---|---|
| [`quickstart.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/quickstart.py) | In-memory client + server loopback (CPython, MicroPython, CircuitPython). |
| [`circuitpython_client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/circuitpython_client.py) | CircuitPython board connecting to a remote `ws://` echo server. |
| [`circuitpython_server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/circuitpython_server.py) | CircuitPython board accepting inbound websocket connections. |

## What's new

*0.3.0 — public `chumicro_websockets.testing` (FakeConnection,
FakeListener, TickClock) + end-to-end client↔server integration suite.*

*0.2.0 — `WebSocketClient` and `WebSocketServer` + `Connection`.
Fragmentation reassembly, oversize policy, auto-pong, optional
auto-ping, full close handshake.*

*0.1.0 — wire-format primitives (`FrameParser`, `encode_frame`,
handshake encoders + parsers, close-payload codec, exception
hierarchy).*

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
