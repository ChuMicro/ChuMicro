# User Guide

## Overview

`chumicro-http-server` serves web pages and JSON from a CircuitPython or MicroPython board, and from CPython for tests.  You register a function for each URL with `@server.route`, and your main loop calls `server.handle(now_ms)` over and over.  Each call accepts a waiting visitor and moves every open request one small step along: read some bytes, run your route once the request is complete, send some bytes.  Then it returns, usually within a few milliseconds, so an LED blink, a sensor read, or a wifi check in the same loop keeps running while the board serves.  There is no `async` and there are no threads.

## Getting started

A server with two routes, joining wifi with `chumicro-wifi`:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))

# The server opens port 8080 on its first handle() call.  radio= matters
# on CircuitPython only; MicroPython ignores it.
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

Open `http://<board address>:8080/` in a browser once `wifi.ip` has an address.  What the pieces do:

- `ticks_ms()` returns a millisecond counter.  Read it once per pass and hand the same value to every service.
- Every ChuMicro service has two methods.  `check(now_ms)` says whether it has work, and `handle(now_ms)` does a small piece of it and returns.  The server's `check()` always returns `True`, because a visitor can arrive at any moment.
- `wifi.connected` holds the server back until the board has an address, since the listening socket can only open after that.
- `transport_factory` is the function the server calls to open its listening socket.  The server calls it on the first `handle()`, so creating an `HttpServer` touches no network.  [Bring your own transport](#bring-your-own-transport) covers listeners other than `chumicro_sockets.listener`.

This loop runs flat out.  To give the CPU a rest, add `time.sleep(0.01)` at the bottom of the loop, as [`examples/simple_server.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server/examples/simple_server.py) does, or let a `Runner` sleep until there is work (see [Runner pattern](#runner-pattern)).

Create the server at startup.  The first use of `HttpServer` loads the server code, a large import, so do it while the board's memory is still in one piece.

## Settings from a deploy

`HttpServer.from_config(config, radio=radio)` builds the server from a flat settings dict, such as the one `chumicro_config.load_runtime_config()` reads after a ChuMicro deploy.  Every key is optional:

| Key | Default |
|---|---|
| `http_server.bind_host` | `"0.0.0.0"`, every interface |
| `http_server.bind_port` | `8080` |
| `http_server.tls.cert_path` and `http_server.tls.key_path` | Unset, so the server speaks plain HTTP.  Set both to serve HTTPS; setting only one raises `MissingConfigKey`. |

`http_server.max_connections`, `http_server.request_timeout_ms`, `http_server.max_request_body_bytes`, `http_server.max_request_line_bytes`, `http_server.max_headers_bytes`, and `http_server.stream_buffer_size` each set the constructor knob of the same name, described under [Limits and per-call budgets](#limits-and-per-call-budgets).

`radio=` is `wifi.radio` on CircuitPython, or `wifi.adapter.radio` from a `WifiService`; MicroPython ignores it.  Any other keyword (`handler=`, `ticks=`, `recv_budget_per_tick=`, `transport_factory=`) goes straight to the constructor and wins over the matching setting.  `examples/simple_server.py` builds its server this way, from an empty dict when nothing was deployed.

## Runner pattern

`chumicro_runner.Runner` runs several services and timed functions in one loop.  Register each one once; then `runner.tick()` gives every one a turn, and `runner.wait(now_ms)` sleeps until the next one has work.  `HttpServer` registers like any other service:

```python
import gc

from chumicro_runner import Runner

def report(now_ms):
    print("free memory:", gc.mem_free(), "bytes")

runner = Runner()
runner.add(wifi)
runner.add(server)
runner.add_periodic(report, period_ms=30_000)

while True:
    now_ms = runner.tick()   # every registered service takes one small step
    runner.wait(now_ms)      # then the board sleeps until a request arrives or report is due
```

`wait()` keeps this loop from spinning: it sleeps on the listening socket until a request arrives or the next `report` is due.  While a request is in progress, the server asks to be woken at least every 20 ms so the request keeps moving.

This loop drops the `wifi.connected` check.  If the server tries to open its socket before the board has an address, `tick()` catches the error and the server tries again on its next turn.

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
* **One trailing parameter**: `"/widgets/<id>"` matches `/widgets/7` and puts `"7"` in `request.path_params["id"]`.  It covers one segment, so `/widgets/7/parts` does not match.  Only the last segment can be a parameter; `/users/<uid>/posts/<pid>` is not supported.

When a request arrives, the server picks one of three answers:

* A route matches the path and the method.  The server calls your function.
* A route matches the path but not the method.  The server answers `405 Method Not Allowed`, with an `Allow:` header listing the methods that path takes.
* No route matches the path.  The server answers `404`, or calls the catch-all `handler=` function if you passed one to `HttpServer(...)`, which suits a static-file fallback or a single-page app.

An exact route wins over a parameter route.  Registering the same path and method twice keeps the last function.

## `Request` and `Response`

A route receives a `Request` and returns a `Response`.

`Request` exposes:

| Attribute | Purpose |
|---|---|
| `request.method` | `"GET"`, `"POST"`, … |
| `request.path` | The path, without the `?query` part. |
| `request.query` | `CaseInsensitiveDict` of the query string, with percent-encoding left as sent.  Keys ignore case, so `?Foo=1&foo=2` becomes one entry with the values joined by `", "`. |
| `request.path_params` | `dict` of the `<param>` segment, when the route has one. |
| `request.headers` | Case-insensitive dict of request headers. |
| `request.body` | Raw `bytes`, or `b""` for a request without a body. |
| `request.peer` | `(host, port)` of the client. |
| `request.text()` | Body decoded with the charset named in `Content-Type`, UTF-8 when none is named.  MicroPython and CircuitPython decode UTF-8 only, so another declared charset raises or mis-decodes there. |
| `request.json()` | Body parsed with `json.loads`. |

`build_response(status, *, body=None, json=None, text=None, html=None, headers=None)` builds a `Response`.  Pass at most one of `body=`, `json=`, `text=`, or `html=`, and it sets the matching `Content-Type`:

```python
build_response(200, json={"ok": True})         # application/json
build_response(200, text="plain text")         # text/plain; charset=utf-8
build_response(200, html="<h1>hi</h1>")        # text/html; charset=utf-8
build_response(200, body=b"\x00\x01\x02")      # raw bytes, no Content-Type set
build_response(204)                            # no body
```

For full control, construct `Response` directly.  Its arguments are keyword-only, `reason` is required, and `body` must be `bytes`; a `str` body turns into a `500` when the server sends it:

```python
Response(status_code=200, reason="OK", headers={"X-Trace": "abc"}, body=b"raw")
```

When a route raises, the server answers `500 Internal Server Error` with the exception message as the body, and carries on serving.  A route that returns something other than a `Response` (one that forgot its `return`, say) gets a `500` too.

## Limits and per-call budgets

The constructor takes limits that stop one client from taking over the board's memory or time.  Each "per tick" budget applies once per `handle()` call:

| Knob | Default | What it bounds |
|---|---|---|
| `max_connections` | `4` | Connections in progress at once.  Sized for a Pi Pico W's heap.  The server stops accepting while all are busy. |
| `request_timeout_ms` | `10000` | Time a connection may take from accept to last byte sent.  A stalled client gets its socket closed. |
| `recv_budget_per_tick` | `1024` | Bytes read per connection per `handle()`, so a big upload cannot stretch one call. |
| `send_budget_per_tick` | `4096` | Bytes sent per connection per `handle()`.  Larger than the read budget so a small response goes out in one call. |
| `max_request_body_bytes` | `16 KB` | Largest request body.  A request declaring a bigger `Content-Length` gets `413 Payload Too Large` before any body memory is allocated.  A body within the cap gets one buffer of exactly its size, freed once the response is sent. |
| `max_request_line_bytes` | `1 KB` | Longest request line (method, target, version).  A line that reaches the cap without ending gets `414 URI Too Long`, so a client dribbling bytes cannot grow it further. |
| `max_headers_bytes` | `4 KB` | Total size of the header lines.  More gets `431 Request Header Fields Too Large`. |
| `stream_buffer_size` | `1 KB` | Buffer for a streaming response (see [Streaming large response bodies](#streaming-large-response-bodies)).  Only a connection that streams allocates one, and it is the whole memory cost of the stream, whatever the body size. |

The read and send budgets keep an LED blink steady while a client uploads a big POST body.

## Connection lifetime

The server answers one request per connection.  Every response carries `Connection: close`, and the socket closes once the response has gone out, so HTTP/1.1 keep-alive is not supported.  Request bodies must come with `Content-Length`; a chunked upload is dropped without an answer.

## Streaming large response bodies

A normal `Response` holds its whole body in memory.  When the body would not fit (a sensor-log dump, a file from storage, a long CSV export), return a **streaming response** instead.  The server pulls the body from your function one small buffer at a time and sends it across many `handle()` calls, so a 264 KB board can serve a body of any size for the cost of one buffer.

Streaming lives in an opt-in submodule, so a server that never streams never loads its code:

```python
from chumicro_http_server.streaming import build_streaming_response, SOURCE_EOF
```

### The byte source

You supply a **source**, a function `source(buffer) -> int`.  Each time the server is ready for more, it hands the source a buffer; the source writes body bytes into it and returns what it did:

| Return | Meaning |
|---|---|
| `n > 0` | Wrote `n` body bytes into `buffer[:n]` (`1 <= n <= len(buffer)`). |
| `0` | No bytes ready yet, but the body is **not** finished, so the server asks again on a later call.  Use this only for a source that can genuinely run dry for a moment, such as a sensor sampled in the background. |
| `SOURCE_EOF` (`-1`) | End of body.  The server finishes the framing and closes. |

`0` means "ask again" and `-1` means "done"; the rest of the contract follows from that.  A source reading a log or a file always has bytes until it runs out, so it never returns `0`: it returns positive counts, then `SOURCE_EOF`.  This source serves a list of records, cutting each to fit the buffer:

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

The server picks the framing from whether you know the total length:

* **Known total**: pass `content_length=`.  The server sends a `Content-Length` header and the body as is.  Your source must then produce exactly that many bytes before `SOURCE_EOF`; a mismatch closes the connection.
* **Unknown total**: leave `content_length` unset, the default.  The server uses `Transfer-Encoding: chunked`, so you do not need the size up front.  The chunk framing is written into the same buffer, with no allocation per chunk.

```python
build_streaming_response(200, source=src, content_length=file_size)  # Content-Length
build_streaming_response(200, source=src)                            # chunked
```

Leave `Content-Length`, `Transfer-Encoding`, and `Connection` out of `headers=`; the server owns framing.  Other headers, such as `Content-Type`, are yours to set.

### Memory, fairness, and timeouts

* **One fixed buffer.**  Each streaming connection allocates one `stream_buffer_size`-byte buffer (default 1 KB) and reuses it for the whole transfer, whatever the body size.  A buffered response never allocates one.  A slow client cannot grow it: the server asks the source for more only after the previous bufferful has gone out.
* **Fair turns.**  A streamed send is capped by the same `send_budget_per_tick` as a buffered response, so one large download cannot starve the other connections.
* **Timeout.**  `request_timeout_ms` covers the whole streamed send, and a client that stops reading is closed when it runs out.  Size `request_timeout_ms` for your largest streamed response.

### Handler failures mid-stream

Once the first body byte is on the wire, the status line has gone out and an error page can no longer replace it.  So if your source raises mid-stream, or produces fewer or more bytes than a declared `Content-Length`, the server closes the connection and the client sees a truncated body.  Do the work that can fail (opening the file, running the first query) before you return the streaming response, where a failure still becomes a clean `500`.

## Bring your own transport

`HttpServer` works with any listener.  The `transport_factory` you pass is a function taking no arguments and returning an object with three methods:

| Method | Contract |
|---|---|
| `accept() -> (socket, address)` | Returns the next client (an object with `recv_into` / `send` / `close` / `setblocking`) and its address.  Raises `OSError(EAGAIN)` when nobody is waiting. |
| `close() -> None` | Stops accepting connections. |
| `setblocking(flag) -> None` | Optional.  The server calls it when present. |

Each accepted socket needs `recv_into(buffer, nbytes) -> int`, `send(payload) -> int`, `close() -> None`, and optionally `setblocking(flag)`, the same methods every other ChuMicro library expects from a TCP socket.

`chumicro_sockets.listener` is one such listener.  A stdlib `socket.socket`, bound, listening, and set non-blocking, is another:

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

With your own listener, a `chumicro-workspace deploy` can leave the default listener code off the board.  Add this line to your `code.py` or `app.py`:

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

Name the module stem, as above, or the full path (`"chumicro_sockets.sockets_factory"`).  A name that matches nothing fails the deploy with a message pointing at the typo.  When `chumicro_sockets.sockets_factory` is missing on the board, skipped this way or never installed, `HttpServer.from_config(...)` raises `RuntimeError` telling you to pass `transport_factory=`.

The server needs nothing else from ChuMicro.  Pass your own `transport_factory`, set `ticks=` to your own clock, call `handle()` from a plain `while` loop, and test your routes against a `FakeSocket` with no board attached ([Testing Helpers](testing.md)).

## TLS server (HTTPS)

For HTTPS, hand the server a TLS listener.  Build an SSL context from your certificate and key with [`chumicro_sockets.ssl_context_with_cert_and_key_paths`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets):

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

With `from_config`, setting `http_server.tls.cert_path` and `http_server.tls.key_path` builds the same TLS listener for you.

Tested on real boards:

| Runtime + board | TLS server | Notes |
|---|---|---|
| CircuitPython on ESP32-S2 (Lolin S2) | ✅ Works | RSA-2048 certificate.  The SSL context takes about 6 KB of heap, and each handshake needs tens of KB more, so leave headroom. |
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) | ❌ Refused (`UnsupportedSSLConfigError`) | `listener(tls=True)` raises up front.  The CYW43 wifi chip's TLS server path fails mid-handshake with `OSError(32)` and leaves wifi wedged until a USB power cycle.  Use an ESP32-family board, or MicroPython on rp2. |
| MicroPython on ESP32-S2 / S3 | ✅ Works | Hardware-accelerated handshake; about 1 KB of heap. |
| MicroPython on rp2 (Pi Pico W) | ✅ Works (RSA-2048 only) | DER-encoded key; about 25 KB of heap per handshake; ECC keys fail when the context is built. |

The board runs each TLS handshake in one go when it accepts the connection, so your loop pauses until the handshake finishes.  After that, the connection goes back to small steps per `handle()` call.  A client that fails its handshake is dropped and counted in `server.accept_errors`, and the server keeps listening.

## Memory notes

- `max_connections` bounds the per-connection memory.  Each connection holds a read buffer of at most 512 B (a `recv_budget_per_tick` above 512 is met with several reads per call), the parsed `Request`, and the encoded `Response` until it has gone out.
- The request body is held once.  The parser's copy is released as soon as the `Request` is built.
- A streaming response adds one `stream_buffer_size` buffer per streaming connection, allocated on first use and reused for the whole transfer.
- The streaming code sits in the opt-in `chumicro_http_server.streaming` submodule and loads only when a route streams, so a server that never streams never pays for it.

## Testing

`chumicro_http_server.testing` ships `FakeListener` and `request_bytes`, so a unit test can push a request through your routes with no network, no port, and no board.  [Testing Helpers](testing.md) has worked examples.

## Platform notes

Works the same on CPython, MicroPython, and CircuitPython.  `chumicro-sockets` handles each runtime's socket differences, and the server uses the non-blocking socket it hands back.

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
