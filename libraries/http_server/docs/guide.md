# User Guide

## Overview

`chumicro-http-server` serves web pages and JSON from a CircuitPython or MicroPython board, and from CPython for tests.  `@server.route` registers a function for each URL.  The main loop calls `server.handle(now_ms)` on every pass.  Each call accepts a waiting visitor and moves every open request one small step along: it reads some bytes, runs the route once the request is complete, or sends some bytes.  The call then returns, usually within a few milliseconds, so an LED blink, a sensor read, or a wifi check in the same loop keeps running while the board serves.

## Getting started

This server answers on two routes and joins wifi with `chumicro-wifi`:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))

# The server opens port 8080 on its first handle() call.
# CircuitPython needs radio=, and MicroPython ignores it.
server = HttpServer(
    transport_factory=lambda: listener("0.0.0.0", 8080, radio=wifi.adapter.radio),
)

@server.route("/")
def home(request):
    return build_response(200, html="<h1>Hello from your board</h1>")

@server.route("/echo", methods=["POST"])
def echo(request):
    return build_response(200, json={"echoed": request.json()})

while True:
    now_ms = ticks_ms()
    if wifi.check(now_ms):                       # join wifi, and rejoin after a drop
        wifi.handle(now_ms)
    if wifi.connected and server.check(now_ms):  # serve once the board has an address
        server.handle(now_ms)
```

Once `wifi.ip` holds an address, open `http://<board address>:8080/` in a browser.

- `ticks_ms()` returns a millisecond counter.  The loop reads it once per pass and hands the same value to every service.
- `check(now_ms)` and `handle(now_ms)` are the two calls every ChuMicro [service](https://chumicro.com/ChuMicro/runner/stable/guide/#services) answers.  The server's `check()` always returns `True`, because a visitor can arrive at any moment.
- `wifi.connected` holds the server back until the board has an address, since the listening socket opens only after that.
- `transport_factory` is the function the server calls to open its listening socket.  The server calls it on the first `handle()`, so creating an `HttpServer` touches no network.  [Bring your own transport](#bring-your-own-transport) covers listeners other than `chumicro_sockets.listener`.

This loop runs flat out.  A `time.sleep(0.01)` at the bottom of the loop rests the CPU, as [`examples/simple_server.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/examples/simple_server.py) does.  A `Runner` sleeps until there is work ([Runner pattern](#runner-pattern)).

Create the server at startup.  The first use of `HttpServer` loads the server code, a large import that needs a large free block of memory.  A board has its largest free blocks right after it starts.

## Settings from a deploy

`HttpServer.from_config(config, radio=radio)` builds the server from a flat settings dict, such as the one `chumicro_config.load_runtime_config()` reads after a ChuMicro deploy.  Every key is optional:

| Key | Default |
|---|---|
| `http_server.bind_host` | `"0.0.0.0"`, every interface |
| `http_server.bind_port` | `8080` |
| `http_server.tls.cert_path` and `http_server.tls.key_path` | Unset, so the server speaks plain HTTP.  Set both to serve HTTPS.  Setting only one raises `MissingConfigKey`. |

`http_server.max_connections`, `http_server.request_timeout_ms`, `http_server.max_request_body_bytes`, `http_server.max_request_line_bytes`, `http_server.max_headers_bytes`, and `http_server.stream_buffer_size` each set the constructor knob of the same name, described under [Limits and per-call budgets](#limits-and-per-call-budgets).

`radio=` is `wifi.radio` on CircuitPython, or `wifi.adapter.radio` from a `WifiService`.  MicroPython ignores it.  Any other keyword, such as `handler=`, `ticks=`, `recv_budget_per_tick=`, or `transport_factory=`, goes straight to the constructor and wins over the matching setting.  `examples/simple_server.py` builds its server this way, from an empty dict when nothing was deployed.

## Runner pattern

`HttpServer` registers with a [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/guide/) `Runner` like any other service.  This loop replaces the one in [Getting started](#getting-started) and prints the board's address every 30 seconds:

```python
from chumicro_runner import Runner

def report(now_ms):
    print("serving at", wifi.ip)

runner = Runner()
runner.add(wifi)
runner.add(server)
runner.add_periodic(report, period_ms=30_000)

while True:
    now_ms = runner.tick()   # every registered job takes one small step
    runner.wait(now_ms)      # then the board sleeps until a request arrives or report is due
```

`runner.wait()` sleeps on the listening socket until a request arrives or the next `report` is due.  While a request is in progress, the server asks to be woken at least every 20 ms so the request keeps moving.

This loop drops the `wifi.connected` check.  When the server tries to open its socket before the board has an address, `tick()` catches the error.  The server tries again on its next step.

## Routing

`@server.route(path, methods=...)` registers a function for a path.  `methods` defaults to `("GET",)`.

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

A path takes one of two forms:

* **Exact**: `"/api/widgets"` matches that path only.
* **One trailing parameter**: `"/widgets/<id>"` matches `/widgets/7` and puts `"7"` in `request.path_params["id"]`.  The parameter covers one segment, so `/widgets/7/parts` falls through to the next rule.  The server matches a `<name>` in any earlier segment as literal text, so `/users/<uid>/posts/<pid>` matches no real request.

When a request arrives, the server answers it one of three ways:

* A route matches the path and the method.  The server calls the route's function.
* A route matches the path but not the method.  The server answers `405 Method Not Allowed`, with an `Allow:` header listing the methods that path takes.
* No route matches the path.  The server answers `404`, or calls the catch-all `handler=` function passed to `HttpServer(...)`.  A catch-all suits a static-file fallback or a single-page app.

An exact route wins over a parameter route.  Registering the same path and method twice keeps the last function.

## `Request` and `Response`

A route receives a `Request` and returns a `Response`.

| `Request` attribute | Holds |
|---|---|
| `request.method` | `"GET"`, `"POST"`, … |
| `request.path` | The path, without the `?query` part. |
| `request.query` | `CaseInsensitiveDict` of the query string, with percent-encoding left as sent.  Keys ignore case, so `?Foo=1&foo=2` becomes one entry with the values joined by `", "`. |
| `request.path_params` | `dict` of the `<param>` segment, when the route has one. |
| `request.headers` | Case-insensitive dict of request headers. |
| `request.body` | Raw `bytes`, or `b""` for a request with no body. |
| `request.peer` | `(host, port)` of the client. |
| `request.text()` | The body decoded with the charset named in `Content-Type`, or UTF-8 when none is named.  MicroPython and CircuitPython decode UTF-8 only, so another declared charset raises or mis-decodes there. |
| `request.json()` | The body parsed with `json.loads`. |

`build_response(status, *, body=None, json=None, text=None, html=None, headers=None)` builds a `Response`.  It takes at most one of `body=`, `json=`, `text=`, or `html=`.  It sets the `Content-Type` that matches:

```python
build_response(200, json={"ok": True})         # application/json
build_response(200, text="plain text")         # text/plain; charset=utf-8
build_response(200, html="<h1>hi</h1>")        # text/html; charset=utf-8
build_response(200, body=b"\x00\x01\x02")      # raw bytes, no Content-Type set
build_response(204)                            # no body
```

For full control, construct `Response` directly.  Its arguments are keyword-only.  `reason` and `headers` are required.  `body` must be `bytes`, because a `str` body turns into a `500` when the server sends it:

```python
Response(status_code=200, reason="OK", headers={"X-Trace": "abc"}, body=b"raw")
```

When a route raises, the server answers `500 Internal Server Error` with the exception message as the body.  The server carries on serving.  A route that returns anything other than a `Response`, such as one that forgot its `return`, also gets a `500`.

## Limits and per-call budgets

The constructor takes limits that keep one client from taking over the board's memory or time.  Each "per tick" budget applies once per `handle()` call:

| Knob | Default | What it bounds |
|---|---|---|
| `max_connections` | `4` | Connections in progress at once, sized for a Pi Pico W's heap.  The server stops accepting while all are busy. |
| `request_timeout_ms` | `10000` | Time a connection may take from accept to last byte sent.  A stalled client gets its socket closed. |
| `recv_budget_per_tick` | `1024` | Bytes read per connection per `handle()`, so a big upload cannot stretch one call. |
| `send_budget_per_tick` | `4096` | Bytes sent per connection per `handle()`.  It is larger than the read budget so a small response goes out in one call. |
| `max_request_body_bytes` | `16 KB` | Largest request body.  A request declaring a bigger `Content-Length` gets `413 Payload Too Large` before any body memory is allocated.  A body within the cap gets one buffer of exactly its size, freed once the response is sent. |
| `max_request_line_bytes` | `1 KB` | Longest request line: method, target, and version.  A line that reaches the cap without ending gets `414 URI Too Long`, so a client dribbling bytes cannot grow it further. |
| `max_headers_bytes` | `4 KB` | Total size of the header lines.  More gets `431 Request Header Fields Too Large`. |
| `stream_buffer_size` | `1 KB` | Buffer for a [streaming response](#streaming-large-response-bodies).  Only a connection that streams allocates one.  That buffer is the whole memory cost of the stream, whatever the body size. |

The read and send budgets keep an LED blink steady while a client uploads a big POST body.

## Connection lifetime

The server answers one request per connection.  Every response carries `Connection: close`.  The socket closes once the response has gone out, so each request opens a new connection.  A request body must come with `Content-Length`.  The server drops a chunked upload without an answer.

## Streaming large response bodies

A normal `Response` holds its whole body in memory.  When the body would not fit, as with a sensor-log dump, a file from storage, or a long CSV export, a route returns a **streaming response**.  The server pulls the body from a function one small buffer at a time and sends it across many `handle()` calls.  A Pi Pico W with 264 KB of RAM serves a body of any size for the cost of one buffer.

Streaming lives in a separate submodule, so a server that never streams never loads its code:

```python
from chumicro_http_server.streaming import build_streaming_response, SOURCE_EOF
```

### The byte source

A streaming response takes a **source**, a function `source(buffer) -> int`.  Each time the server is ready for more, it hands the source a buffer.  The source writes body bytes into it and returns one of these:

| Return | Meaning |
|---|---|
| `n > 0` | Wrote `n` body bytes into `buffer[:n]` (`1 <= n <= len(buffer)`). |
| `0` | No bytes are ready yet and the body continues, so the server asks again on a later call.  This suits a source that can run dry for a moment, such as a sensor sampled in the background. |
| `SOURCE_EOF` (`-1`) | End of body.  The server finishes the framing and closes. |

A source reading a log or a file has bytes until it runs out.  It returns positive counts, then `SOURCE_EOF`.  This source serves a list of records, cutting each to fit the buffer:

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

### Framing: Content-Length or chunked

The server picks the framing from whether the total length is known:

* **Known total**: pass `content_length=`.  The server sends a `Content-Length` header and the body as is.  The source must then produce exactly that many bytes before `SOURCE_EOF`.  A mismatch closes the connection.
* **Unknown total**: leave `content_length` unset, the default.  The server uses `Transfer-Encoding: chunked`, which needs no size up front.  The chunk framing is written into the same buffer, with no allocation per chunk.

```python
build_streaming_response(200, source=src, content_length=file_size)  # Content-Length
build_streaming_response(200, source=src)                            # chunked
```

The server sets `Content-Length`, `Transfer-Encoding`, and `Connection` itself, so leave them out of `headers=`.  Set any other header, such as `Content-Type`, in `headers=`.

### Memory, fairness, and timeouts

* **One fixed buffer.**  Each streaming connection allocates one `stream_buffer_size`-byte buffer and reuses it for the whole transfer, whatever the body size.  A buffered response allocates none.  A slow client cannot grow the buffer, because the server asks the source for more only after the previous bufferful has gone out.
* **Fair steps.**  A streamed send is capped by the same `send_budget_per_tick` as a buffered response, so one large download leaves time for the other connections.
* **Timeout.**  `request_timeout_ms` covers the whole streamed send.  The server closes a client that stops reading once that time runs out.  Size `request_timeout_ms` for the largest streamed response.

### Source failures mid-stream

Once the first body byte is on the wire, the status line has gone out, so an error page can no longer replace it.  A source that raises mid-stream, or that produces fewer or more bytes than a declared `Content-Length`, makes the server close the connection.  The client then sees a truncated body.  Do the work that can fail, such as opening the file or running the first query, before returning the streaming response.  A failure there still becomes a clean `500`.

## Bring your own transport

`HttpServer` works with any listener.  `transport_factory` is a function that takes no arguments and returns a listener with these methods:

| Method | Contract |
|---|---|
| `accept() -> (socket, address)` | Returns the next client and its address.  Raises `OSError(EAGAIN)` when nobody is waiting. |
| `close() -> None` | Stops accepting connections. |
| `setblocking(flag) -> None` | Optional.  The server calls it when present. |

Each accepted socket needs `recv_into(buffer, nbytes) -> int`, `send(payload) -> int`, `close() -> None`, and optionally `setblocking(flag)`.

`chumicro_sockets.listener` is one such listener.  A stdlib `socket.socket`, bound, listening, and set non-blocking, is another.  This program serves one page from a laptop through it:

```python
import socket as stdlib_socket
import time

from chumicro_http_server import HttpServer, build_response
from chumicro_timing import ticks_ms

def make_listener():
    listener = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_STREAM)
    listener.setsockopt(stdlib_socket.SOL_SOCKET, stdlib_socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", 8080))
    listener.listen(4)
    listener.setblocking(False)
    return listener

server = HttpServer(transport_factory=make_listener)

@server.route("/")
def home(request):
    return build_response(200, text="served through a stdlib socket")

while True:
    now_ms = ticks_ms()
    if server.check(now_ms):
        server.handle(now_ms)
    time.sleep(0.01)
```

A program that supplies its own listener can keep `chumicro-sockets` off the board with one line in `code.py` or `app.py`:

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

[Slimming your deploy](https://chumicro.com/ChuMicro/guides/contributing/slimming-your-deploy/) explains the line.  On a board without `chumicro_sockets.sockets_factory`, `HttpServer.from_config(...)` raises `RuntimeError` asking for `transport_factory=`.

With its own `transport_factory`, its own clock as `ticks=`, and `handle()` called from a plain `while` loop, the server needs no other ChuMicro library.  Unit tests drive routes through a fake listener with no board attached ([Testing Helpers](testing.md)).

## TLS server (HTTPS)

For HTTPS, hand the server a TLS listener.  [`chumicro_sockets.ssl_context_with_cert_and_key_paths`](https://chumicro.com/ChuMicro/sockets/stable/guide/#accepting-connections) builds an SSL context from a certificate file and a key file:

```python
from chumicro_sockets import (
    listener,
    ssl_context_with_cert_and_key_paths,
)

ssl_context = ssl_context_with_cert_and_key_paths(
    "/cert.pem",     # CircuitPython needs file paths, not bytes
    "/key.der",      # MicroPython on rp2 needs a DER key
)

def open_listener():
    # wifi is the WifiService from Getting started.
    return listener(
        "0.0.0.0", 8443,
        tls=True, context=ssl_context, radio=wifi.adapter.radio,
    )

server = HttpServer(transport_factory=open_listener)
```

With `from_config`, the `http_server.tls.cert_path` and `http_server.tls.key_path` settings build the same TLS listener.

Tested on real boards:

| Runtime + board | TLS server | Notes |
|---|---|---|
| CircuitPython on ESP32-S2 (Lolin S2) | ✅ Works | RSA-2048 certificate.  The SSL context takes about 6 KB of heap.  Each handshake needs tens of KB more, so leave headroom. |
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) | ❌ Refused (`UnsupportedSSLConfigError`) | `listener(tls=True)` raises up front.  The `chumicro-sockets` [quirks table](https://chumicro.com/ChuMicro/sockets/stable/guide/#runtime-and-chip-quirks) gives the reason.  Use an ESP32-family board, or MicroPython on rp2. |
| MicroPython on ESP32-S2 / S3 | ✅ Works | Hardware-accelerated handshake, about 1 KB of heap. |
| MicroPython on rp2 (Pi Pico W) | ✅ Works (RSA-2048 only) | DER-encoded key, about 25 KB of heap per handshake.  An ECC key fails when the context is built. |

The board runs each TLS handshake in one go when it accepts the connection, so the loop pauses until the handshake finishes.  After that, the connection goes back to small steps per `handle()` call.  A client that fails its handshake is dropped and counted in `server.accept_errors`.  The server keeps listening.

## Memory notes

- `max_connections` bounds the per-connection memory.  Each connection holds a read buffer of at most 512 B, the parsed `Request`, and the encoded `Response` until it has gone out.  A `recv_budget_per_tick` above 512 is met with several reads per call.
- The server holds the request body once.  The parser releases its copy as soon as the `Request` is built.
- A streaming response adds one `stream_buffer_size` buffer per streaming connection, allocated on first use and reused for the whole transfer.
- The streaming code sits in the `chumicro_http_server.streaming` submodule and loads only when a route streams.

## Testing

`chumicro_http_server.testing` ships `FakeListener` and `request_bytes`, so a unit test pushes a request through the routes with no network, no port, and no board.  [Testing Helpers](testing.md) has worked examples.

## Platform notes

The server works the same on CPython, MicroPython, and CircuitPython.  `chumicro-sockets` handles each runtime's socket differences.  The server uses the non-blocking socket it hands back.  [TLS server (HTTPS)](#tls-server-https) lists the boards that serve HTTPS.

## Examples

| Example | What it shows |
|---|---|
| [`examples/simple_server.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/examples/simple_server.py) | Serves an HTML page, a JSON status route, and a POST echo route, and prints a status line every 30 seconds while it waits for visitors.  Open it in a browser or drive it with `curl`.  Runs on CircuitPython and MicroPython. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
