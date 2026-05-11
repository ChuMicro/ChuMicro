# User Guide

## Overview

`chumicro-http-server` is a non-blocking HTTP/1.1 server that runs on CircuitPython, MicroPython, and CPython.  Each connection is a state machine the server advances one chunk per tick — an LED keeps blinking, a control loop keeps running, sensor reads keep happening, all while requests are being served.  Built on `chumicro-sockets` (TCP listener + accepted client sockets) and `chumicro-timing` (ticks) only; no `async`, no threads, no `chumicro-requests` dependency on the device.


## Getting started

A minimal, hello-world server with one route:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms

server = HttpServer(
    listener_factory=lambda: tcp_listening_socket(
        host="0.0.0.0", port=8080, radio=wifi.radio,
    ),
)

@server.route("/")
def index(request):
    return build_response(200, html="<h1>Hello from a Pi Pico W</h1>")

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
```

`listener_factory` is a callable — the listener opens lazily on the first `handle()` call so construction is side-effect-free and unit-testable against a `FakeSocket`.

## Routing

`@server.route(path, methods=...)` registers a handler:

```python
@server.route("/")                                # GET /
def index(request):
    return build_response(200, text="hi")

@server.route("/api/sensor", methods=["POST"])    # POST /api/sensor
def post_sensor(request):
    payload = request.json()
    return build_response(201, json={"ok": True})

@server.route("/api/temp", methods=["GET", "DELETE"])
def temp(request):
    if request.method == "DELETE":
        return build_response(204)
    return build_response(200, json={"temp_c": 21.5})
```

Two route shapes are supported:

* **Exact match** — `"/api/widgets"`.  O(1) lookup.
* **Single trailing parameter** — `"/widgets/<id>"`.  The matched segment populates `request.path_params["id"]`.  Multi-parameter routes (`/users/<uid>/posts/<pid>`) are a v2 ask.

Method dispatch:

* Path matched, method matched → handler runs.
* Path matched, method not registered → automatic `405 Method Not Allowed` with an `Allow:` header.
* Path not matched → 404, or fall through to a bare `handler=` callable if you set one (catch-all shape, slice-7a-style).

## `Request` and `Response`

The handler signature is `(Request) -> Response`.

`Request` exposes:

| Attribute | Purpose |
|---|---|
| `request.method` | `"GET"`, `"POST"`, … |
| `request.path` | Path before `?`. |
| `request.query` | `dict` from the query string. |
| `request.path_params` | `dict` of `<param>` segments. |
| `request.headers` | Case-insensitive dict. |
| `request.body` | Raw `bytes` (or `b""` for body-less requests). |
| `request.text()` | Body decoded per `Content-Type`'s charset. |
| `request.json()` | Body parsed via `chumicro_msgpack`-compatible `json` import. |

`build_response(status_code, *, body=None, json=None, text=None, html=None, headers=None)` is the convenience builder — pass exactly one of `body=` / `json=` / `text=` / `html=` and it sets the right `Content-Type`:

```python
build_response(200, json={"ok": True})         # application/json
build_response(200, text="plain text")         # text/plain; charset=utf-8
build_response(200, html="<h1>hi</h1>")        # text/html; charset=utf-8
build_response(200, body=b"\x00\x01\x02")      # application/octet-stream (default)
build_response(204)                            # no body
```

For full control, construct `Response(status_code, headers, body)` directly.

## Tick-fairness knobs

The constructor exposes per-connection budgets so you can tune for your workload:

| Knob | Default | What it bounds |
|---|---|---|
| `max_connections` | `4` | Cap on simultaneous in-flight connections.  Sized for Pi Pico W heap. |
| `request_timeout_ms` | `5000` | Per-connection deadline.  Stalled clients get the socket closed. |
| `recv_budget_per_tick` | `1024` | Bytes drained per connection per `handle()`.  Bounds tick latency under big uploads. |
| `send_budget_per_tick` | `4096` | Bytes flushed per connection per `handle()`.  Higher than recv so small responses drain in one tick. |
| `max_request_body_bytes` | `16 KB` | Cap on a single buffered request body.  Bigger bodies → 400. |

Defaults are conservative; the per-tick budgets keep an LED blink visible even with a chatty client and a big POST body.

## TLS server (HTTPS)

`HttpServer` is transport-agnostic — its `listener_factory` returns whatever listener you give it.  For HTTPS, build a TLS-wrapped listener via [`chumicro_sockets.ssl_context_with_cert_and_key_paths`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets):

```python
from chumicro_sockets import (
    tcp_listening_socket,
    ssl_context_with_cert_and_key_paths,
)

ssl_context = ssl_context_with_cert_and_key_paths(
    "/cert.pem",     # CP needs paths, not bytes
    "/key.der",      # MP rp2 needs DER (no PEM_PARSE_C in firmware)
)

def open_listener():
    plain = tcp_listening_socket(host="0.0.0.0", port=8443, radio=wifi.radio)
    return ssl_context.wrap_socket(plain, server_side=True)

server = HttpServer(listener_factory=open_listener)
```

Per-board status from live verification:

| Runtime + board | TLS server | Notes |
|---|---|---|
| CircuitPython on ESP32-S2 | ✅ Works | ~6 KB context + ~35 KB handshake heap. |
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) | ❌ Refused (`UnsupportedSSLConfigError`) | `wrap_socket(server_side=True) + accept()` raises `OSError(32)` mid-handshake AND wedges the CYW43 chip's station-mode state until USB power-cycle. Use ESP32-family for HTTPS on CP. |
| MicroPython on ESP32-S2 / S3 | ✅ Works | Hardware-accelerated; ~1 KB heap. |
| MicroPython on rp2 (Pi Pico W) | ✅ Works (RSA-2048 only) | DER-encoded key required; ECC keys fail at context build. |

The TLS handshake is synchronous inside `wrap_socket(..., server_side=True)` — budget for a ~100–500 ms listener stall during accept.  After the handshake, the server's per-connection state machine resumes its runner-friendly progression.

## Memory notes

Connection state is bounded by `max_connections`; each connection holds its receive buffer (`recv_budget_per_tick`-sized chunks), the parsed `Request`, and the encoded `Response` until drained.  Nothing else allocates per-tick steady-state.  The shared `chumicro-requests` HTTP/1.1 wire primitives (case-insensitive header dict, charset parsing) are inlined into `chumicro_http_server._wire` so a server-only board doesn't ship the client library.

## Platform notes

Works identically on CPython, MicroPython, and CircuitPython.  The `chumicro-sockets` listener provides the platform-specific socket plumbing; the server just consumes the resulting non-blocking socket.

## Examples

| Example | What it shows |
|---|---|
| [`examples/simple_server.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/examples/simple_server.py) | Single-board HTTP server with `GET /`, `GET /api/uptime`, `POST /api/echo` routes; drive it with `curl` from your laptop.  Cross-runtime (CP + MP); runtime marker gates hardware-only deploys.  For a two-board (server + client) pattern, see the workspace template's `two_board_handshake/` example. |

## v1 non-goals

WebSockets, sessions / cookies / auth helpers, multipart upload, sub-app mounting, async handlers.  Out of scope for the v1 surface; reopen if a real consumer needs them.

## What's new

- **0.1.2**: TLS-server matrix surfaced; doc + framing fixes.
- **0.1.1**: Routing decorator + per-tick budgets + multi-connection support.
- **0.1.0**: Initial library — listener + parser + canned response (slice 7a).

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
