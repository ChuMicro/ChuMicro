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
    now = ticks_ms()
    if server.check(now):
        server.handle(now)
```

`listener_factory` is a callable — the listener opens lazily on the first `handle()` call so construction is side-effect-free and unit-testable against a `FakeSocket`.

## Runner pattern

`HttpServer` implements the runner contract (`check(now_ms)` / `handle(now_ms)`) — register it with `chumicro_runner.Runner` and it gets ticked alongside your other services:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(server)
runner.add_periodic(led_blink, period_ms=500)

while True:
    runner.tick()
```

`check(now_ms) -> bool` reports whether the server has work pending; `handle(now_ms)` does at most one tick of progress, capped by the per-connection budgets below.

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
* **Single trailing parameter** — `"/widgets/<id>"`.  The matched segment populates `request.path_params["id"]`.  Multi-parameter routes (`/users/<uid>/posts/<pid>`) are not supported.

Method dispatch:

* Path matched, method matched → handler runs.
* Path matched, method not registered → automatic `405 Method Not Allowed` with an `Allow:` header.
* Path not matched → 404, or fall through to a bare `handler=` callable if you set one (catch-all — useful for a static-file fallback or single-page app).

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
| `request.json()` | Body parsed via `json.loads` — UTF-8 in, Python types out. |

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
| `request_timeout_ms` | `10000` | Per-connection deadline.  Stalled clients get the socket closed. |
| `recv_budget_per_tick` | `1024` | Bytes drained per connection per `handle()`.  Bounds tick latency under big uploads. |
| `send_budget_per_tick` | `4096` | Bytes flushed per connection per `handle()`.  Higher than recv so small responses drain in one tick. |
| `max_request_body_bytes` | `16 KB` | Cap on a single buffered request body.  Requests declaring a larger `Content-Length` get a `413 Payload Too Large` response — no body bytes are allocated.  Within the cap, the body buffer is sized-to-fit at headers-complete time (one `bytearray(content_length)` allocation per request), freed when the response drains. |

Defaults are conservative; the per-tick budgets keep an LED blink visible even with a chatty client and a big POST body.

## Connection lifetime

Each request is served on a fresh accepted socket; every response includes `Connection: close` and the socket is closed once the response drains.  HTTP/1.1 keep-alive and connection pooling are not supported.  Chunked request bodies are not supported either — use `Content-Length`.

## Bring your own transport

`HttpServer` doesn't care which library produces its listener.  The `listener_factory` you pass is a zero-arg callable returning any object exposing the three-method contract:

| Method | Contract |
|---|---|
| `accept() -> (socket, address)` | Returns the next accepted client (a TCP-shaped object with `recv_into` / `send` / `close` / `setblocking`) plus the peer's address.  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no connection is pending. |
| `close() -> None` | Stops accepting new connections. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

Each accepted socket must in turn expose `recv_into(buffer, nbytes) -> int`, `send(payload) -> int`, `close() -> None`, and best-effort `setblocking(flag)` — the same shape every other chumicro library expects from a TCP-like object.

`chumicro_sockets.tcp_listening_socket` / `tls_listening_socket` is one valid producer.  Stdlib `socket.socket` bound + listening after `setblocking(False)` is another:

```python
import socket as stdlib_socket

def make_listener():
    listener = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_STREAM)
    listener.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", 8080))
    listener.listen(4)
    listener.setblocking(False)
    return listener

server = HttpServer(listener_factory=make_listener, handler=...)
```

If you supply your own listener and want `chumicro_sockets` dropped from the deploy entirely, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

Family form (the bare stem) or exact path (`"chumicro_http_server.sockets_factory"`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `HttpServer.from_config(...)` when `chumicro_http_server.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwarg.

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
| CircuitPython on ESP32-S2 | ✅ Works | Bench-tested ~5 KB heap for `SSLContext` + `load_cert_chain` + `wrap_socket(server_side=True)` on a listening socket (RSA-2048 self-signed cert).  Each incoming connection adds heap during handshake — leave tens of KB of headroom. |
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) | ❌ Refused (`UnsupportedSSLConfigError`) | `wrap_socket(server_side=True) + accept()` raises `OSError(32)` mid-handshake AND wedges the CYW43 chip's station-mode state until USB power-cycle. Use ESP32-family for HTTPS on CP. |
| MicroPython on ESP32-S2 / S3 | ✅ Works | Hardware-accelerated; ~1 KB heap. |
| MicroPython on rp2 (Pi Pico W) | ✅ Works (RSA-2048 only) | DER-encoded key required; ECC keys fail at context build. |

The TLS handshake is synchronous inside `wrap_socket(..., server_side=True)` — the listener stalls until the handshake completes (single-digit to tens of milliseconds on the supported board class with a local TLS client; longer on a slow uplink as TLS rounds-trip).  After the handshake, the server's per-connection state machine resumes its runner-friendly progression.

## Memory notes

Connection state is bounded by `max_connections`; each connection holds its receive buffer (`recv_budget_per_tick`-sized chunks), the parsed `Request`, and the encoded `Response` until drained.  Nothing else allocates per-tick steady-state.  The shared `chumicro-requests` HTTP/1.1 wire primitives (case-insensitive header dict, charset parsing) are inlined into `chumicro_http_server._wire` so a server-only board doesn't ship the client library.

## Platform notes

Works identically on CPython, MicroPython, and CircuitPython.  The `chumicro-sockets` listener provides the platform-specific socket plumbing; the server just consumes the resulting non-blocking socket.

## Examples

| Example | What it shows |
|---|---|
| [`examples/simple_server.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/examples/simple_server.py) | Single-board HTTP server with `GET /`, `GET /api/uptime`, `POST /api/echo` routes; drive it with `curl` from your laptop.  Cross-runtime (CP + MP); runtime marker gates hardware-only deploys. |

## Not included

WebSockets, sessions / cookies / auth helpers, multipart upload, sub-app mounting, async handlers — out of scope for now.  Reach for [`chumicro-websockets`](https://chumicro.github.io/ChuMicro/websockets/stable/) for the websocket case.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
