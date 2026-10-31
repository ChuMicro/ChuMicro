# User Guide

## Overview

`chumicro-requests` makes HTTP requests from a board without stopping the program around them.  Every request goes through three moves:

1. **Start it.**  `client.get(url)` (or `post`, `put`, `patch`, `delete`) returns a `RequestHandle` straight away.  Nothing has gone over the network yet.
2. **Move it along.**  Your loop calls `client.handle(now_ms)` on every pass.  Each call takes one small step (look up the host, connect, send, read whatever bytes have arrived) and returns.
3. **Collect it.**  Once `request.done` is `True`, `request.response` holds the answer, or `request.error` says why there is none.

If you know `adafruit_requests`, moves 1 and 3 are its `response = requests.get(url)` split in two.  The split lets the rest of your loop (an LED, a button, a sensor) keep running while the server takes its time.  Opening the connection is the one step that can still hold your loop, and [Platform notes](#platform-notes) lists which parts of it do on each runtime.

One client runs one request at a time.  Calling `get()` while a request is still in flight raises `HttpBusyError`, so finish one request before starting the next, or build a second `HttpClient`.

## Getting started

A CircuitPython `code.py` that fetches a page every 30 seconds, the same loop as the [`periodic_get.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/periodic_get.py) example.  Put your network name and password in the `connect()` call:

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

What each piece does:

- `connector_factory(radio=wifi.radio)` builds the `transport_factory`, a function `HttpClient` calls to open a connection for each request.  CircuitPython needs the board's radio here.  On MicroPython and CPython, call `connector_factory()` with no arguments.
- `client.get(url)` starts the request.  It raises only for a URL it cannot parse (`HttpURLError`) or when a request is already in flight (`HttpBusyError`).  Network failures arrive later, on `request.error`.
- `client.check(now_ms)` returns `True` while a request is in flight, and `client.handle(now_ms)` takes one step on it.  A `Runner` from `chumicro-runner` calls this same check-then-handle pair on every service it drives, which is how the client joins a runner loop unchanged ([Runner pattern](#runner-pattern)).
- `ticks_ms()` from `chumicro-timing` is a millisecond counter.  The client times its requests on the same counter, so pass its value rather than one from `time.monotonic()`.
- `Rate(30_000, now_ms)` makes `due(now_ms)` true once every 30 seconds.  A `time.sleep(30)` in its place would stop the whole loop, which is what this library exists to avoid.

Build your client at startup.  The first `HttpClient` reference imports the client module, so let that one-time cost land on a fresh heap.

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

`request.result` folds the two checks from the loop into one line: it returns `request.response`, or raises `request.error` when the request failed.  Reading it before `request.done` raises `HttpError`.

`response.text` decodes `body` with `response.encoding`, which comes from the `charset=` part of the `Content-Type` header and falls back to `utf-8`.  When a server names the wrong charset, set the encoding before reading `text`:

```python
response.encoding = "latin-1"
print(response.text)
```

`response.json()` decodes through `text`, so the override applies to JSON too.  `response.url` is the URL that answered, after any redirects.

## Writing the fetch as a generator

A generator function is a Python function with `yield` in it.  Python can pause it at each `yield` and resume it later on the same line, and a `Runner` from `chumicro-runner` does the pausing and resuming for you.  `chumicro_requests.generators.get` is built for that: `response = yield from get(connector, url)` pauses your function until the whole response is in, then hands back the `Response`.  The fetch reads like `adafruit_requests` code, and the board keeps running everything else while it waits.

This is the [`generator_fetch.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/requests/examples/generator_fetch.py) example without the wifi setup:

```python
from chumicro_requests import HttpError
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_add, ticks_ms

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
- `runner.tick()` resumes each registered generator whose wait is over, and `runner.wait(now_ms)` rests the CPU until a socket has data or a timer is due.  Those two lines are the whole main loop.  Anything else you register with the same runner runs between fetches.
- `sleep_until(ticks_add(ticks_ms(), 30_000))` pauses the function for 30 seconds without stopping the board.
- A failed request raises inside your function, on the `yield from` line: an `HttpError` from the request, or an `OSError` when the runner sees the connection drop.  Catch it there to print and try again.  An error you leave uncaught stops `fetch_forever` for good; the runner counts it in `runner.handler_errors` and carries on with everything else.

The same module has `post`, `put`, `patch`, `delete`, the general `fetch(connector, method, url)`, and `stream(...)` for bodies too big for RAM ([Streaming large bodies](#streaming-large-bodies)).  Each call builds its own client, so a generator fetch never raises `HttpBusyError`.  A body over `max_body_bytes` raises `HttpOversizedError` here instead of being dropped.

## Runner pattern

When a board does several things at once, register each one with a `Runner` and let it call `check` and `handle` for you.  `HttpClient` has the `check(now_ms)` / `handle(now_ms)` pair a runner expects, so `runner.add(client)` is all it takes.  Pass `on_done=` to `get()` and the client calls your function with the finished `RequestHandle`:

```python
from chumicro_runner import Runner

URL = "http://example.com/"


def show(request):
    if request.error is not None:
        print("failed:", request.error)
    else:
        print(request.response.status_code, len(request.response.body), "bytes")


def start_fetch(now_ms):
    if not client.busy:
        client.get(URL, on_done=show)


runner = Runner()
runner.add(client)                                                    # moves the request along
runner.add_periodic(start_fetch, period_ms=30_000, start_after_ms=0)  # every 30 s, starting now
runner.add_periodic(blink, period_ms=500)                             # your LED, on its own timer

while True:
    now_ms = runner.tick()  # every registered service takes one small step
    runner.wait(now_ms)     # then the CPU rests until the next event or deadline
```

`client` is the `HttpClient` from [Getting started](#getting-started), and `blink(now_ms)` is your own function.  `runner.wait()` watches the client's socket and its timeout, so the loop rests until bytes arrive instead of spinning.

## Sending data: POST, PUT, PATCH, DELETE

Each verb has its own method.  A body can be bytes, a `str`, or a Python object that `json=` encodes for you:

```python
# Raw bytes or a str
request = client.post("http://example.com/widgets", body=b"\x01\x02\x03")
request = client.post("http://example.com/widgets", body="plain text")

# json= encodes the object and sets Content-Type: application/json
request = client.post("http://example.com/widgets", json={"name": "thing", "qty": 3})

# PUT and PATCH take the same body= and json=
request = client.put("http://example.com/widgets/42", json={"name": "renamed"})
request = client.patch("http://example.com/widgets/42", body=b"diff-bytes")

# DELETE sends no body
request = client.delete("http://example.com/widgets/42")
```

Each line starts one request, so finish it (as in [Getting started](#getting-started)) before starting the next.  Pass `body=` or `json=`, never both; both together raise `ValueError`.  Every verb takes `headers=` as a dict or a list of `(name, value)` pairs, and a `Content-Type` you set there wins over the one `json=` adds.

## Timeouts and errors

Every request has a deadline that covers the whole exchange, first step to last byte, redirects included.  It is 10 seconds unless you change it per request with `timeout_ms=`, or for every request with `HttpClient(default_timeout_ms=...)`:

```python
request = client.get(url, timeout_ms=30_000)
```

The client checks the deadline between steps, so a connect step that holds the loop ([Platform notes](#platform-notes)) can run past it before the timeout lands.  `client.cancel()` ends the request in flight at once, and its handle finishes with an `HttpError`.

Every error is an `HttpError` or one of its subclasses:

| Error | Means |
|---|---|
| `HttpTimeoutError` | The request ran past its deadline. |
| `HttpProtocolError` | The server sent something that is not valid HTTP/1.1, or closed the connection partway through the response. |
| `HttpURLError` | The URL is not an absolute `http://` or `https://` URL.  `get()` raises it at once; a bad redirect `Location` arrives on `request.error`. |
| `HttpOversizedError` | A body ran past `max_body_bytes` under the `DISCONNECT` policy ([Memory notes](#memory-notes)). |
| `HttpBusyError` | `get()` was called while another request was in flight.  Raised by `get()` itself. |
| `HttpError` | The connection failed (host not found, refused, reset) or the request was cancelled. |

## Redirects

`HttpClient` follows `301`, `302`, `303`, `307`, and `308` redirects, up to 5 hops unless you change the limit:

```python
request = client.get(url, max_redirects=0)     # hand back the 3xx response itself
request = client.get(url, max_redirects=20)    # allow more hops for this request

client = HttpClient(transport_factory=connector_factory(radio=wifi.radio), default_max_redirects=10)
```

- `301`, `302`, and `303` repeat the request as a GET with no body, as browsers do (RFC 7231 §6.4).
- `307` and `308` repeat it with the original method and body.
- `Location` can be absolute (`https://other.example/dest`), start at the root (`/api/v2`), or be relative to the current path (`trinkets`).
- `response.url` is the final URL, after every hop.
- When the hop limit runs out, you get the last 3xx response back rather than an error.

## Body framing

`HttpClient` reads a response body one of three ways, picked from the response headers:

- **`Content-Length: N`** reads exactly N bytes.  Most servers send this.
- **`Transfer-Encoding: chunked`** decodes the chunks and joins them (RFC 7230 §4.1).  Chunk extensions and trailer headers are read and discarded, and `Content-Length` is ignored when both headers are present.
- **Neither header** reads until the server closes the connection.

`response.body`, `text`, and `json()` behave the same whichever way the body arrived.  Any other `Transfer-Encoding`, such as `gzip` or `deflate`, fails the request with `HttpProtocolError` rather than handing you compressed bytes.

## Streaming large bodies

By default the whole body lands in RAM, capped at `max_body_bytes` (64 KB).  Pass `stream=True` to any verb to read the body a piece at a time instead.  Firmware images, log pulls, and any payload bigger than the heap then cost a fixed amount of RAM: a staging window of `stream_buffer_size` bytes (1024 by default) plus your own buffer.

```python
request = client.get("http://example.com/firmware.bin", stream=True, timeout_ms=120_000)
buffer = bytearray(512)
view = memoryview(buffer)
```

Then, on each pass through your loop after `client.handle(now_ms)`:

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

How a streamed request behaves:

- `request.response` appears as soon as the final hop's headers arrive, before `request.done`, so you can check `status_code` and `headers` first.  Its `body` is `b""` and `streamed` is `True`; `text` and `json()` raise `HttpError`.
- `request.read_body_into(buffer)` copies body bytes into your buffer and returns the count.  `0` means nothing has arrived yet; once `request.done` is `True` with no `error`, `0` means the body is finished.
- When the staging window is full, the client stops reading the socket until you drain it, and stops asking a `Runner` to watch the socket, so the loop rests instead of spinning on data it cannot take.
- `max_body_bytes` and `WhenOversized` do not apply: the staging window is the RAM limit.  To enforce a size limit of your own, count what you read and call `client.cancel()`.
- `timeout_ms` covers the whole transfer, your reads included, so size it for the download rather than the first byte.
- `client.cancel()` ends the download at once; the handle finishes with an `HttpError`.

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

An `https://` URL works with no extra setup.  The connection checks the server's certificate against a default set of trusted root certificates, which comes from a different place on each runtime:

| Runtime | Default trusted roots |
|---|---|
| CircuitPython | The root certificates built into the firmware |
| MicroPython | A curated set of common public roots that `chumicro-sockets` ships |
| CPython | The operating system's trust store |

To trust a particular certificate authority instead (a server on your own network, or a site whose root the MicroPython set lacks), build a context from its PEM file and pass it to `connector_factory`:

```python
from chumicro_sockets import ssl_context_with_ca

with open("/my_root_ca.pem") as pem_file:
    context = ssl_context_with_ca(pem_file.read())
client = HttpClient(transport_factory=connector_factory(radio=wifi.radio, ssl_context=context))
```

### Set the board's clock first

The certificate check compares the certificate's start date with the board's clock.  A board with no battery-backed clock boots with a date years in the past, before any current certificate was issued, and the handshake fails with `ValueError("certificate validity starts in the future")`.  Set the clock from the network with [`chumicro-ntp`](https://chumicro.com/ChuMicro/ntp/stable/) before the first `https://` request.

### Leave heap room for the handshake

A TLS handshake on a MicroPython board measured about 25 KB of heap on top of what the program already held.  When that much is not free, the connect fails with `OSError(12)` (ENOMEM), which reaches you as an `HttpError` on `request.error`.  Two things help: import less before the first `https://` request, and, if you deploy with `chumicro-workspace`, pass `--deploy-mode flash` so the library files live on the board's filesystem instead of in RAM.

## Bring your own transport

`HttpClient` opens every connection through the `transport_factory` you pass it, a function called as `transport_factory(host, port, use_tls)` once per request and once per redirect hop.  `connector_factory` from `chumicro-sockets` is the one most programs use.  Write your own to run over a different network stack.

The factory returns a connector, an object that opens the connection one step at a time.  `HttpClient` uses these parts of it:

| Member | What `HttpClient` expects |
|---|---|
| `tick(now_ms)` | Take one step toward an open connection. |
| `state` | `"ready"` once connected, `"failed"` once it has given up, anything else while still working. |
| `socket` | The connected socket, once `state` is `"ready"`. |
| `last_error` | Why it failed, once `state` is `"failed"`. |
| `io_socket`, `io_interest(now_ms)` | The socket to watch, and whether to watch it for reading or writing, so a `Runner` can rest until it is ready. |
| `cancel()` | Give up and close whatever is open. |

The connected socket needs four methods:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no data is waiting, returns 0 when the peer has closed, otherwise returns the bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns the bytes sent, which may be fewer than `len(payload)`. |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Optional.  The client calls it when present. |

To leave `chumicro-sockets` off the board when you supply your own factory, add this to your entry file and the `chumicro-workspace` deployer drops the default factory from what it copies:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

The entry accepts the bare module stem (`"sockets_factory"`, matching every `chumicro_*.sockets_factory`) or one exact dotted path (`"chumicro_sockets.sockets_factory"`).  An entry that matches nothing fails the deploy with a typo message.  With the default factory absent, `HttpClient.from_config(...)` raises `RuntimeError` asking for `transport_factory=`.

`chumicro-requests` needs nothing else from ChuMicro to run: pass your own `transport_factory` (and, if you like, your own `ticks=` clock) and drive the client from a plain `while` loop as in [Getting started](#getting-started).  For host tests, a factory returning `chumicro_sockets.testing.FakeSocketConnector` runs a request end to end with no network.

## Memory notes

- A buffered body is capped at `max_body_bytes`, 64 KB by default, a size picked for a 256 KB board.  Raise it on a board with more RAM.  The `when_oversized=` policy decides what happens past the cap: `WhenOversized.DROP_WITH_EVENT` (the default) finishes the request with an empty body, sets `response.oversized_dropped`, and calls `client.on_oversized(reported_length, url)`.  `DROP_SILENT` does the same without the call, and `DISCONNECT` fails the request with `HttpOversizedError`.
- `handle()` reads at most `recv_budget_per_tick` bytes per call (1024 by default), so a large download cannot take over one pass of your loop.
- Response headers have their own cap, `max_header_bytes` (16 KB by default).  Raise it if a server's cookies or header chain overflow it.
- `stream=True` keeps a body of any size to the `stream_buffer_size` window plus your own buffer ([Streaming large bodies](#streaming-large-bodies)).

## Testing

`chumicro_requests.testing.FakeHttpClient` stands in for `HttpClient` in host tests.  Script each answer with `enqueue_response()` or `enqueue_error()`, and the next `handle()` call finishes the request.  [Testing Helpers](testing.md) walks through it.

## Platform notes

The same code runs on CircuitPython, MicroPython, and CPython once the network is up.  The runtimes differ in which connect steps hold your loop until they finish:

| Step | CircuitPython | MicroPython | CPython |
|---|---|---|---|
| DNS lookup | Holds the loop | Holds the loop | Holds the loop |
| TCP connect | Holds the loop | Small steps | Small steps |
| TLS handshake (`https://` only) | Holds the loop | Holds the loop | Small steps |
| Sending, waiting for the server, reading the response | Small steps | Small steps | Small steps |

A slow or unreachable host can hold the loop for seconds in the first three rows, so start requests before time-critical work rather than in the middle of it.

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
