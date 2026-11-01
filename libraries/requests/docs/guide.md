# User Guide

## Overview

`chumicro-requests` makes HTTP requests from a board while the rest of the program keeps running.

1. **Start it.**  `client.get(url)` (or `post`, `put`, `patch`, `delete`) returns a `RequestHandle` straight away.  Nothing has gone over the network yet.
2. **Move it along.**  The loop calls `client.handle(now_ms)` on every pass.  Each call takes one small step, such as looking up the host, connecting, sending, or reading the bytes that have arrived, and returns.
3. **Collect it.**  Once `request.done` is `True`, `request.response` holds the answer, or `request.error` says why there is none.

Steps 1 and 3 are `adafruit_requests`' `response = requests.get(url)` split in two.  Between them, the rest of the loop, such as an LED, a button, or a sensor, keeps running while the server takes its time.  Opening the connection is the one step that can still hold the loop ([Platform notes](#platform-notes)).

One client runs one request at a time.  Calling `get()` while a request is still in flight raises `HttpBusyError`.  A program finishes one request before starting the next, or builds a second `HttpClient`.

## Getting started

This CircuitPython `code.py` fetches a page every 30 seconds, the same loop as the [`periodic_get.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/periodic_get.py) example.  The `connect()` call takes the network name and password:

```python
import wifi
from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import Rate, ticks_ms

wifi.radio.connect("your-network", "your-password")
client = HttpClient(transport_factory=connector_factory(radio=wifi.radio))
every_30_s = Rate(30_000, ticks_ms())
request = client.get("http://example.com/")  # starts the fetch and returns at once

while True:
    now_ms = ticks_ms()
    if client.check(now_ms):    # True while a request is in flight
        client.handle(now_ms)   # one small step: connect, send, or read

    if request is not None and request.done:
        if request.error is not None:
            print("failed:", request.error)
        else:
            print(request.response.status_code, len(request.response.body), "bytes")
        request = None

    if request is None and every_30_s.due(now_ms):
        request = client.get("http://example.com/")
```

- `connector_factory(radio=wifi.radio)` builds the `transport_factory`, a function `HttpClient` calls to open a connection for each request.  CircuitPython needs the board's radio here.  On MicroPython and CPython, `connector_factory()` takes no arguments.
- `client.get(url)` starts the request.  It raises only for a URL it cannot parse (`HttpURLError`) or when a request is already in flight (`HttpBusyError`).  Network failures arrive later, on `request.error`.
- `client.check(now_ms)` returns `True` while a request is in flight.  `client.handle(now_ms)` takes one step on it.  The same pair makes the client a runner service ([Runner pattern](#runner-pattern)).
- `ticks_ms()` from `chumicro-timing` is a millisecond counter.  The client times its requests on the same counter, so the loop passes its value rather than one from `time.monotonic()`.
- `Rate(30_000, now_ms)` makes `due(now_ms)` true once every 30 seconds ([`chumicro-timing`](https://chumicro.com/ChuMicro/timing/stable/guide/)).  A `time.sleep(30)` in its place would stop the whole loop.

The first reference to `HttpClient` imports the client module.  Building the client at startup lands that one-time cost on a fresh heap.

## Reading the response

```python
response = request.result                  # the Response, or raises request.error
print(response.status_code)                # 200
print(response.reason)                     # OK
print(response.headers["content-type"])    # header names match in any case
print(response.body)                       # raw bytes
print(response.text)                       # body decoded to str
print(response.json())                     # body parsed as JSON
```

`request.result` folds the two checks from the loop into one line.  It returns `request.response`, or raises `request.error` when the request failed.  Reading it before `request.done` raises `HttpError`.

`response.text` decodes `body` with `response.encoding`.  The encoding comes from the `charset=` part of the `Content-Type` header and falls back to `utf-8`.  When a server names the wrong charset, setting the encoding before reading `text` overrides it:

```python
response.encoding = "latin-1"
print(response.text)
```

`response.json()` decodes through `text`, so the override applies to JSON too.

## Writing the fetch as a generator

`chumicro_requests.generators.get` fetches inside a [generator task](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks).  `response = yield from get(connector, url)` pauses the task until the whole response is in, then hands back the `Response`.  The fetch reads like `adafruit_requests` code, and the board keeps running everything else while it waits.

This CircuitPython program is a short form of the [`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) example:

```python
import wifi
from chumicro_requests import HttpError
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_add, ticks_ms

wifi.radio.connect("your-network", "your-password")
connector = connector_factory(radio=wifi.radio)


def fetch_forever():
    while True:
        try:
            response = yield from get(connector, "http://example.com/")
            print(response.status_code, len(response.body), "bytes")
        except (HttpError, OSError) as error:
            print("failed:", error)
        yield from sleep_until(ticks_add(ticks_ms(), 30_000))


runner = Runner()
runner.add_generator(fetch_forever())

while True:
    now_ms = runner.tick()  # fetch_forever runs when what it waits for is ready
    runner.wait(now_ms)     # the CPU rests until then
```

- `runner.add_generator(fetch_forever())` registers the function and runs it up to its first pause.
- `runner.tick()` and `runner.wait(now_ms)` are the whole main loop.  Anything else registered with the same runner runs between fetches.
- `sleep_until(ticks_add(ticks_ms(), 30_000))` pauses the function for 30 seconds without stopping the board.
- A failed request raises inside the function, on the `yield from` line.  It raises an `HttpError` from the request, or an `OSError` when the runner sees the connection drop.  The `except` there prints the error, and the loop tries again.  An uncaught error ends `fetch_forever` for good.  The runner counts it in `runner.handler_errors` and carries on with everything else.

The same module has `post`, `put`, `patch`, `delete`, the general `fetch(connector, method, url)`, and `stream(...)` for bodies too big for RAM ([Streaming large bodies](#streaming-large-bodies)).  Each call builds its own client, so a generator fetch never raises `HttpBusyError`.  A body over `max_body_bytes` raises `HttpOversizedError` here instead of being dropped.

## Runner pattern

`HttpClient` is a [runner service](https://chumicro.com/ChuMicro/runner/stable/guide/#services), so `runner.add(client)` is all the wiring it needs.  `client.get(url, on_done=show)` makes the client call `show` with the finished `RequestHandle`:

```python
import wifi
from chumicro_requests import HttpClient
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory

URL = "http://example.com/"

wifi.radio.connect("your-network", "your-password")
client = HttpClient(transport_factory=connector_factory(radio=wifi.radio))


def show(request):
    if request.error is not None:
        print("failed:", request.error)
    else:
        print(request.response.status_code, len(request.response.body), "bytes")


def start_fetch(now_ms):
    if not client.busy:
        client.get(URL, on_done=show)


def heartbeat(now_ms):
    print("still running")


runner = Runner()
runner.add(client)                                                    # moves the request along
runner.add_periodic(start_fetch, period_ms=30_000, start_after_ms=0)  # every 30 s, starting now
runner.add_periodic(heartbeat, period_ms=5_000)                       # other work, on its own timer

while True:
    now_ms = runner.tick()  # every registered service takes one small step
    runner.wait(now_ms)     # then the CPU rests until the next event or deadline
```

`runner.wait()` watches the client's socket and its timeout, so the loop rests until bytes arrive.

## Sending data: POST, PUT, PATCH, DELETE

`post`, `put`, `patch`, and `delete` each start a request with that HTTP verb.  A body can be bytes, a `str`, or a Python object that `json=` encodes:

| Call | Body sent |
|---|---|
| `client.post(url, body=b"\x01\x02\x03")` | The raw bytes |
| `client.post(url, body="plain text")` | The `str`, encoded as UTF-8 |
| `client.post(url, json={"name": "thing", "qty": 3})` | The object as JSON, with `Content-Type: application/json` |
| `client.put(url, json={"name": "renamed"})` | `put` and `patch` take the same `body=` and `json=` as `post` |
| `client.patch(url, body=b"diff-bytes")` | The raw bytes |
| `client.delete(url)` | No body |

One request has to finish before the next starts on the same client ([Getting started](#getting-started)).  `body=` and `json=` together raise `ValueError`.  Every verb takes `headers=` as a dict or a list of `(name, value)` pairs.  A `Content-Type` set there wins over the one `json=` adds.

## Timeouts and errors

Every request has a deadline that covers the whole exchange, first step to last byte, redirects included.  The deadline is 10 seconds by default.  `timeout_ms=` changes it for one request, and `HttpClient(default_timeout_ms=...)` changes it for every request:

```python
request = client.get(url, timeout_ms=30_000)
```

The client checks the deadline between steps, so a connect step that holds the loop ([Platform notes](#platform-notes)) can run past it before the timeout lands.  `client.cancel()` ends the request in flight at once.  Its handle finishes with an `HttpError`.

Every error is an `HttpError` or one of its subclasses:

| Error | Means |
|---|---|
| `HttpTimeoutError` | The request ran past its deadline. |
| `HttpProtocolError` | The server sent something that is not valid HTTP/1.1, or closed the connection partway through the response. |
| `HttpURLError` | The URL is not an absolute `http://` or `https://` URL.  `get()` raises it at once.  A bad redirect `Location` arrives on `request.error`. |
| `HttpOversizedError` | A body ran past `max_body_bytes` under the `DISCONNECT` policy ([Memory notes](#memory-notes)). |
| `HttpBusyError` | `get()` was called while another request was in flight.  Raised by `get()` itself. |
| `HttpError` | The connection failed (host not found, refused, reset) or the request was cancelled. |

## Redirects

`HttpClient` follows `301`, `302`, `303`, `307`, and `308` redirects, up to 5 hops by default.  `max_redirects=0` hands back the 3xx response itself:

```python
request = client.get(url, max_redirects=0)
```

`max_redirects=20` allows more hops for one request.  `HttpClient(..., default_max_redirects=10)` changes the limit for every request.

- `301`, `302`, and `303` repeat the request as a GET with no body, as browsers do (RFC 7231 §6.4).
- `307` and `308` repeat it with the original method and body.
- `Location` can be absolute (`https://other.example/dest`), start at the root (`/api/v2`), or be relative to the current path (`trinkets`).
- `response.url` is the final URL, after every hop.
- When the hop limit runs out, the request finishes with the last 3xx response instead of an error.

## Body framing

`HttpClient` picks how to read a response body from the response headers:

- **`Content-Length: N`** reads exactly N bytes.  Most servers send this.
- **`Transfer-Encoding: chunked`** decodes the chunks and joins them (RFC 7230 §4.1).  Chunk extensions and trailer headers are read and discarded, and `Content-Length` is ignored when both headers are present.
- **Neither header** reads until the server closes the connection.

`response.body`, `text`, and `json()` behave the same whichever way the body arrived.  Any other `Transfer-Encoding`, such as `gzip` or `deflate`, fails the request with `HttpProtocolError` instead of handing back compressed bytes.

## Streaming large bodies

By default the whole body lands in RAM, capped at `max_body_bytes` (64 KB).  `stream=True` on any verb reads the body a piece at a time instead.  Firmware images, log pulls, and any payload bigger than the heap then cost a fixed amount of RAM: a staging window of `stream_buffer_size` bytes (1024 by default) plus the program's own buffer.

```python
request = client.get("http://example.com/firmware.bin", stream=True, timeout_ms=120_000)
buffer = bytearray(512)
view = memoryview(buffer)
```

Each pass through the loop, after `client.handle(now_ms)`, reads what has arrived:

```python
if request is not None:
    if request.error is not None:
        print("download failed:", request.error)
        request = None
    elif request.response is not None:          # the headers are in
        count = request.read_body_into(view)
        if count:
            flash.write(view[:count])           # your code: store this piece
        elif request.done:
            print("download complete")          # 0 after done means end of body
            request = None
```

- `request.response` appears as soon as the final hop's headers arrive, before `request.done`, so the program can check `status_code` and `headers` first.  Its `body` is `b""` and its `streamed` is `True`.  `text` and `json()` raise `HttpError`.
- `request.read_body_into(buffer)` copies body bytes into the buffer and returns the count.  `0` means nothing has arrived yet, until `request.done` is `True` with no `error`.  From then on, `0` means the body is finished.
- When the staging window is full, the client stops reading the socket until the program drains it.  It also stops asking a `Runner` to watch the socket, so the loop rests instead of spinning on data it cannot take.
- `max_body_bytes` and `WhenOversized` leave a streamed body alone, since the staging window is the RAM limit.  A program that wants its own size limit counts what it reads and calls `client.cancel()`.
- `timeout_ms` covers the whole transfer, the program's reads included, so it is sized for the download rather than the first byte.

The generator form reads one piece per `yield from`:

```python
from chumicro_requests.generators import stream


def download(connector, url, store):
    reader = yield from stream(connector, "GET", url, timeout_ms=120_000)
    if reader.response.status_code != 200:
        reader.cancel()
        return
    buffer = bytearray(512)
    view = memoryview(buffer)
    while True:
        count = yield from reader.read_into(view)
        if count == 0:
            break
        store(view[:count])


runner.add_generator(download(connector, url, flash.write))
```

## HTTPS

An `https://` URL works with no extra setup.  The connection checks the server's certificate against each runtime's default trusted roots, listed in the sockets guide's [TLS](https://chumicro.com/ChuMicro/sockets/stable/guide/#tls) section.

A context built from one certificate authority's PEM file trusts that CA instead, for a server on a home network or a site whose root the MicroPython set lacks.  `connector_factory` takes it as `ssl_context=`:

```python
from chumicro_sockets import ssl_context_with_ca

with open("/my_root_ca.pem") as pem_file:
    context = ssl_context_with_ca(pem_file.read())
client = HttpClient(transport_factory=connector_factory(radio=wifi.radio, ssl_context=context))
```

### Set the board's clock first

The certificate check compares the certificate's start date with the board's clock.  A board with no battery-backed clock boots with a date years in the past, before any current certificate was issued.  The handshake then fails with `ValueError("certificate validity starts in the future")`.  [`chumicro-ntp`](https://chumicro.com/ChuMicro/ntp/stable/) sets the clock from the network before the first `https://` request.

### Leave heap room for the handshake

A TLS handshake on a MicroPython board measured about 25 KB of heap on top of what the program already held.  Without that much free, the connect fails with `OSError(12)` (ENOMEM), which arrives as an `HttpError` on `request.error`.  Importing less before the first `https://` request leaves more room.  A `chumicro-workspace` deploy with `--deploy-mode flash` keeps the library files on the board's filesystem instead of in RAM.

## Bring your own transport

`HttpClient` opens every connection through its `transport_factory`, a function called as `transport_factory(host, port, use_tls)` once per request and once per redirect hop.  Most programs use `connector_factory` from `chumicro-sockets`.  A custom factory runs the client over a different network stack.

The factory returns a connector, an object that opens the connection one step at a time.  `HttpClient` uses these parts of it:

| Member | What `HttpClient` expects |
|---|---|
| `tick(now_ms)` | Take one step toward an open connection. |
| `state` | `"ready"` once connected, `"failed"` once it has given up, anything else while still working. |
| `socket` | The connected socket, once `state` is `"ready"`. |
| `last_error` | Why it failed, once `state` is `"failed"`. |
| `io_socket`, `io_interest(now_ms)` | The socket to watch, and whether to watch it for reading or writing, so a `Runner` can rest until it is ready. |
| `cancel()` | Give up and close whatever is open. |

The connected socket needs these methods:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no data is waiting, returns 0 when the peer has closed, otherwise returns the bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns the bytes sent, which may be fewer than `len(payload)`. |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Optional.  The client calls it when present. |

With a custom factory, this line in the entry file makes the `chumicro-workspace` deployer drop the default factory, and `chumicro-sockets` with it:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

Each entry is a bare module stem (`"sockets_factory"`, matching every `chumicro_*.sockets_factory`) or one exact dotted path (`"chumicro_sockets.sockets_factory"`).  An entry that matches nothing fails the deploy with a typo message.  With the default factory absent, `HttpClient.from_config(...)` raises `RuntimeError` asking for `transport_factory=`.

With its own `transport_factory` and `ticks=` clock, `chumicro-requests` runs with no other ChuMicro library, driven from a plain `while` loop like the one in [Getting started](#getting-started).  For host tests, a factory returning `chumicro_sockets.testing.FakeSocketConnector` runs a request end to end with no network.

## Memory notes

- A buffered body is capped at `max_body_bytes`, 64 KB by default, a size picked for a 256 KB board.  A board with more RAM can raise it.
- The `when_oversized=` policy decides what happens past the cap.  `WhenOversized.DROP_WITH_EVENT`, the default, finishes the request with an empty body, sets `response.oversized_dropped`, and calls `client.on_oversized(reported_length, url)`.  `DROP_SILENT` does the same without the call.  `DISCONNECT` fails the request with `HttpOversizedError`.
- `handle()` reads at most `recv_budget_per_tick` bytes per call (1024 by default), so a large download cannot take over one pass of the loop.
- Response headers have their own cap, `max_header_bytes` (16 KB by default).  A server with large cookies or a long header chain needs it raised.

## Testing

`chumicro_requests.testing.FakeHttpClient` stands in for `HttpClient` in host tests.  `enqueue_response()` or `enqueue_error()` scripts each answer, and the next `handle()` call finishes the request.  [Testing Helpers](testing.md) walks through it.

## Platform notes

The same code runs on CircuitPython, MicroPython, and CPython once the network is up.  Sending, waiting for the server, and reading the response take small steps on every runtime.  The connect steps that hold the loop on each runtime are listed in the sockets guide's [Platform notes](https://chumicro.com/ChuMicro/sockets/stable/guide/#platform-notes).  A slow or unreachable host can hold the loop for seconds in those steps, so a program starts requests before time-critical work instead of in the middle of it.

## Examples

| Example | What it shows |
|---|---|
| [`periodic_get.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/periodic_get.py) | Fetches a page every 30 seconds from a plain `while True` loop that calls `client.check` and `client.handle`, and prints the status and size of each answer.  CircuitPython and MicroPython. |
| [`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) | The same job written as `response = yield from get(...)` in a generator function, run by a `Runner` loop.  CircuitPython and MicroPython. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
