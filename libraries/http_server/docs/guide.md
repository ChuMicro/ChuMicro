# User Guide

## Overview

`chumicro-http-server` is a non-blocking HTTP/1.1 server that runs on CircuitPython, MicroPython, and CPython.  Each connection is a state machine the server advances one chunk per tick — an LED keeps blinking, a control loop keeps running, sensor reads keep happening, all while requests are being served.  Built on `chumicro-sockets` (TCP listener + accepted client sockets) and `chumicro-timing` (ticks) only; no `async`, no threads, no `chumicro-requests` dependency on the device.

## Getting started

A minimal, hello-world server with one route:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_timing import ticks_ms

server = HttpServer(
    transport_factory=lambda: listener(
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

Build your server at startup. The first `HttpServer` reference imports the server module, so let that one-time cost land on a fresh heap.

`transport_factory` is a callable — the listener opens lazily on the first `handle()` call so construction is side-effect-free and unit-testable against a `FakeSocket`.

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
| `request.text()` | Body decoded per `Content-Type`'s charset. Only UTF-8 decodes on every runtime — MicroPython and CircuitPython ship a UTF-8-only `str` codec, so a declared non-UTF-8 charset raises or mis-decodes there. |
| `request.json()` | Body parsed via `json.loads` — UTF-8 in, Python types out. |

`build_response(status_code, *, body=None, json=None, text=None, html=None, headers=None)` is the convenience builder — pass exactly one of `body=` / `json=` / `text=` / `html=` and it sets the right `Content-Type`:

```python
build_response(200, json={"ok": True})         # application/json
build_response(200, text="plain text")         # text/plain; charset=utf-8
build_response(200, html="<h1>hi</h1>")        # text/html; charset=utf-8
build_response(200, body=b"\x00\x01\x02")      # raw bytes, no Content-Type set
build_response(204)                            # no body
```

For full control, construct `Response` directly — its arguments are keyword-only and `reason` is required, and `body` must be `bytes` (a `str` body is rejected as a 500 at send time):

```python
Response(status_code=200, reason="OK", headers={"X-Trace": "abc"}, body=b"raw")
```

## Tick-fairness knobs

The constructor exposes per-connection budgets so you can tune for your workload:

| Knob | Default | What it bounds |
|---|---|---|
| `max_connections` | `4` | Cap on simultaneous in-flight connections.  Sized for Pi Pico W heap. |
| `request_timeout_ms` | `10000` | Per-connection deadline.  Stalled clients get the socket closed. |
| `recv_budget_per_tick` | `1024` | Bytes drained per connection per `handle()`.  Bounds tick latency under big uploads. |
| `send_budget_per_tick` | `4096` | Bytes flushed per connection per `handle()`.  Higher than recv so small responses drain in one tick. |
| `max_request_body_bytes` | `16 KB` | Cap on a single buffered request body.  Requests declaring a larger `Content-Length` get a `413 Payload Too Large` response — no body bytes are allocated.  Within the cap, the body buffer is sized-to-fit at headers-complete time (one `bytearray(content_length)` allocation per request), freed when the response drains. |
| `max_request_line_bytes` | `1 KB` | Cap on the request-line length (method + target + version).  A request line that reaches the cap without a CRLF gets a `414 URI Too Long` response, so a no-CRLF dribble can't grow the parse buffer past the cap before the request times out. |
| `max_headers_bytes` | `4 KB` | Cap on the total header-section bytes (every header line plus its CRLF).  Headers exceeding the cap get a `431 Request Header Fields Too Large` response. |
| `stream_buffer_size` | `1 KB` | Staging-window size for a streaming response (see [Streaming large response bodies](#streaming-large-response-bodies)).  Allocated lazily — only a connection that streams pays it — and reused for the whole transfer, so it is the entire per-stream RAM cost regardless of body size. |

Defaults are conservative; the per-tick budgets keep an LED blink visible even with a chatty client and a big POST body.

## Connection lifetime

Each request is served on a fresh accepted socket; every response includes `Connection: close` and the socket is closed once the response drains.  HTTP/1.1 keep-alive and connection pooling are not supported.  Chunked request bodies are not supported either — use `Content-Length`.

## Streaming large response bodies

A normal `Response` holds its whole body in RAM.  When the body is bigger than the heap — a sensor-log dump, a file off storage, a long CSV export — return a **streaming response** instead: the server pulls the body from a callable one small window at a time and drains it to the client across ticks, so a 264 KB board can serve a body of any size at a fixed RAM cost.

Streaming lives in an opt-in submodule (like `chumicro_requests.generators`) — import it explicitly.  A server that never streams never loads its code:

```python
from chumicro_http_server.streaming import build_streaming_response, SOURCE_EOF
```

### The byte source

You supply a **source** — a fill-a-buffer callable `source(buffer) -> int`.  Each tick the server hands it the staging buffer; the source writes body bytes into it and returns what it did:

| Return | Meaning |
|---|---|
| `n > 0` | Wrote `n` body bytes into `buffer[:n]` (`1 <= n <= len(buffer)`). |
| `0` | No bytes ready this tick, but the body is **not** finished — the server retries on a later tick.  Use this only for a source that can genuinely be empty for a tick (a sensor sampled asynchronously). |
| `SOURCE_EOF` (`-1`) | End of body.  The server finalizes the framing and closes. |

The `0`-vs-`SOURCE_EOF` split is the whole contract: `0` means "ask again", `-1` means "done".  A source over a log or file that always has bytes until it runs out never returns `0` — it returns positive counts and then `SOURCE_EOF`.  A five-line generator that emits a list of records, chunking each to the buffer:

```python
def make_source(records):
    pending = bytearray()
    iterator = iter(records)
    def source(buffer):
        while not pending:
            try:
                pending.extend(next(iterator))   # bytes per record
            except StopIteration:
                return SOURCE_EOF                 # no more records
        take = min(len(buffer), len(pending))
        buffer[:take] = pending[:take]
        del pending[:take]
        return take
    return source

@server.route("/log")
def log_dump(request):
    return build_streaming_response(200, source=make_source(read_log_records()))
```

### Framing: Content-Length vs chunked

The server picks the framing from whether you know the total length:

* **Known total** — pass `content_length=`.  The server sends a `Content-Length` header and frames the body raw.  Your source must then produce exactly that many bytes before `SOURCE_EOF`; a mismatch breaks framing and closes the connection.
* **Unknown total** — leave `content_length` unset (the default).  The server uses `Transfer-Encoding: chunked`, so you don't need to know the size up front.  Chunk framing is written into the staging buffer in place — no per-chunk allocation.

```python
build_streaming_response(200, source=src, content_length=file_size)  # Content-Length
build_streaming_response(200, source=src)                            # chunked
```

Do not set `Content-Length` / `Transfer-Encoding` / `Connection` in `headers=` yourself — the server owns framing.  Other headers (e.g. `Content-Type`) are yours to set.

### RAM, fairness, and timeouts

* **Fixed staging window.**  Each streaming connection allocates one `stream_buffer_size`-byte buffer (default 1 KB, constructor knob), reused for the whole transfer — the entire per-stream RAM cost, independent of body size.  It is minted lazily, so a buffered response never allocates one.  A stalled client never grows it: the source is polled for the next fill only after the current one has fully drained to the socket.
* **Per-tick fairness.**  A streamed send is bounded by the same `send_budget_per_tick` a buffered response uses, so one large download can't starve other connections — every connection gets at most one budget slice per `handle()` tick.
* **Timeout.**  `request_timeout_ms` bounds the whole streamed send, and a client that stops reading (sends keep returning EAGAIN) is closed when the deadline fires.  Size `request_timeout_ms` for your largest streamed response, the same way `chumicro_requests`' streamed reads size their `timeout_ms` for the download.

### Handler failures mid-stream

Once the first body byte is on the wire the response is committed — an error page can no longer be spliced in.  So if your source raises mid-stream, or under-/over-runs a declared `Content-Length`, the connection is closed (the client sees a truncated body) and the failure goes through the server's normal fail-and-close path.  Do all the work that can fail — opening the file, the first query — before you return the `StreamingResponse`, where it can still become a clean `500`.

## Bring your own transport

`HttpServer` doesn't care which library produces its listener.  The `transport_factory` you pass is a zero-arg callable returning any object exposing the three-method contract:

| Method | Contract |
|---|---|
| `accept() -> (socket, address)` | Returns the next accepted client (a TCP-shaped object with `recv_into` / `send` / `close` / `setblocking`) plus the peer's address.  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no connection is pending. |
| `close() -> None` | Stops accepting new connections. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

Each accepted socket must in turn expose `recv_into(buffer, nbytes) -> int`, `send(payload) -> int`, `close() -> None`, and best-effort `setblocking(flag)` — the same shape every other chumicro library expects from a TCP-like object.

`chumicro_sockets.listener` is one valid producer.  Stdlib `socket.socket` bound + listening after `setblocking(False)` is another:

```python
import socket as stdlib_socket

def make_listener():
    listener = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_STREAM)
    listener.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", 8080))
    listener.listen(4)
    listener.setblocking(False)
    return listener

server = HttpServer(transport_factory=make_listener, handler=...)
```

If you supply your own listener and want `chumicro_sockets` dropped from the deploy entirely, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

Family form (the bare stem) or exact path (`"chumicro_sockets.sockets_factory"`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `HttpServer.from_config(...)` when `chumicro_sockets.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwarg.

For the full single-library adoption recipe — your transport, your `ticks=`, the runner-less drive loop, and host tests with no board — see [Standalone integration](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/standalone-integration.md).

## TLS server (HTTPS)

`HttpServer` is transport-agnostic — its `transport_factory` returns whatever listener you give it.  For HTTPS, build a TLS-wrapped listener via [`chumicro_sockets.ssl_context_with_cert_and_key_paths`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets):

```python
from chumicro_sockets import (
    listener,
    ssl_context_with_cert_and_key_paths,
)

ssl_context = ssl_context_with_cert_and_key_paths(
    "/cert.pem",     # CP needs paths, not bytes
    "/key.der",      # MP rp2 needs DER (no PEM_PARSE_C in firmware)
)

def open_listener():
    return listener(
        host="0.0.0.0", port=8443,
        tls=True, context=ssl_context, radio=wifi.radio,
    )

server = HttpServer(transport_factory=open_listener)
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

Connection state is bounded by `max_connections`; each connection holds its receive buffer (a scratch chunk capped at 512 B, so a `recv_budget_per_tick` above 512 is satisfied by several `recv_into` calls per tick), the parsed `Request`, and the encoded `Response` until drained.  Nothing else allocates per-tick steady-state.  A streaming response adds one `stream_buffer_size` window (default 1 KB) per streaming connection, minted lazily and reused for the transfer — a body of any size costs that fixed window, never the whole body.  The shared `chumicro-requests` HTTP/1.1 wire primitives (case-insensitive header dict, charset parsing) are inlined into `chumicro_http_server._wire` so a server-only board doesn't ship the client library.  The streamed-body framing code lives in the opt-in `chumicro_http_server.streaming` submodule, loaded only when a handler actually streams, so a buffered-only server never pays its footprint.

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
