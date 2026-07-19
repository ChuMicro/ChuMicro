# User Guide

## Overview

`chumicro-requests` is a non-blocking HTTP/1.1 client built on `chumicro-sockets`.  `HttpClient` is the single entry point for every verb — its `check(now_ms)` / `handle(now_ms)` methods drive the request forward one tick at a time.  An LED keeps blinking on the same board while a request is in flight or mid-timeout against a stalled peer.  Two connect phases are the exception: the DNS lookup, and on MicroPython / CircuitPython the TLS handshake, each block the reactor for their duration (see *Bring your own transport*).  The library is single-in-flight today — a second `client.get(...)` while another request is running raises `HttpBusyError`.

## Getting started with generators

The generator surface runs a whole request top to bottom (connect, send, receive, return) with no handle to poll and no `on_done` callback.  A single `response = yield from get(...)` drives the request under `Runner.add_generator`, and other runner services keep getting the CPU between yields.

```python
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory

transport_factory = connector_factory(radio=wifi.radio)


def fetch_once():
    response = yield from get(transport_factory, "http://api.example.com/now")
    print(response.status_code, len(response.body))


runner = Runner()
handle = runner.add_generator(fetch_once())
while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

`chumicro_requests.generators` also exposes `post`, `put`, `patch`, `delete`, and the lower-level `fetch(transport_factory, method, url)`.  For a body too big for RAM, `stream(...)` returns a reader you pull one chunk per `yield from` (see [Streaming large bodies](#streaming-large-bodies)).

## Getting started with a service

Reach for the `HttpClient` service when you make repeated requests on one client, or when you want the `check` / `handle` shape that drops straight into a `Runner` alongside other services.

```python
from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_ms

client = HttpClient(transport_factory=connector_factory(radio=wifi.radio))
handle = client.get("http://api.example.com/now", timeout_ms=5000)

while not handle.done:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())

response = handle.result
print(response.status_code, response.body)
print(response.text)               # decoded str
print(response.json())             # parsed JSON
```

Build your client at startup. The first `HttpClient` reference imports the client module, so let that one-time cost land on a fresh heap.

## POST / PUT / PATCH / DELETE

`HttpClient` exposes a method per verb. Bodies can be raw bytes / str
or a Python object that gets JSON-encoded:

```python
# Raw bytes / str body
handle = client.post("http://api/widgets", body=b"<custom-bytes>")
handle = client.post("http://api/widgets", body="text/plain payload")

# JSON helper — auto-encodes + sets Content-Type: application/json
handle = client.post("http://api/widgets", json={"name": "thing", "qty": 3})

# PUT / PATCH share the same body / json semantics
handle = client.put("http://api/widgets/42", json={"name": "renamed"})
handle = client.patch("http://api/widgets/42", body=b"diff-bytes")

# DELETE is intransitive in v1 — no body parameter
handle = client.delete("http://api/widgets/42")
```

Caller-supplied `headers={"Content-Type": "..."}` always wins over the
JSON-helper default. Pass exactly one of `body=` or `json=`; passing
both raises `ValueError`.

## Redirects

`HttpClient` follows `301` / `302` / `303` / `307` / `308` redirects
automatically up to a budget. Default cap is 5. Override per-call or
per-client:

```python
# Per-call: don't follow at all (return the 3xx response as-is)
handle = client.get(url, max_redirects=0)

# Per-call: raise the cap
handle = client.get(url, max_redirects=20)

# Per-client default
client = HttpClient(transport_factory=..., default_max_redirects=10)
```

Method handling follows long-standing browser + RFC 7231 §6.4 rules:

- `301` / `302` / `303` switch the next hop to **GET with no body**
- `307` / `308` **preserve** the original method and body

`response.url` reflects the URL of the FINAL hop, not the original
request. If the budget is exhausted before reaching a non-3xx response,
the last 3xx is returned to the caller (matching CPython `requests`'
default behavior without the `raise_for_status()` step).

The `Location` header may be absolute (`https://other.com/dest`),
absolute-path (`/api/v2`), or path-relative (`trinkets`). All three
shapes are resolved against the current URL.

## Body framing

`HttpClient` accepts three RFC 7230 body framings transparently:

- **`Content-Length: N`** — read exactly N bytes (most common case).
- **`Transfer-Encoding: chunked`** — RFC 7230 §4.1 chunked decode.
  Chunk-extensions and trailer headers are accepted and discarded.
  `Content-Length` is ignored when chunked is present per §3.3.3.
- **Neither header** — read until the peer closes the connection
  (HTTP/1.0-style framing).

In all cases `response.body` returns the decoded bytes (chunks
concatenated for chunked responses).  `response.text` and
`response.json()` work the same way regardless of framing.

Other `Transfer-Encoding` values (`gzip`, `deflate`, `identity`
stacked with chunked, etc.) are rejected with `HttpProtocolError`
in v1 — the caller would otherwise silently get garbled bytes.

## Streaming large bodies

By default the whole body is buffered in RAM, capped at
`max_body_bytes` (64 KB).  Pass `stream=True` — on any verb, or on the
generic `client.request(method, url, ...)` — to consume the body
incrementally instead: firmware images, log pulls, and any payload
bigger than the heap become readable at a fixed RAM cost (the
`stream_buffer_size` staging window, default 1024 bytes, plus your own
buffer).

```python
handle = client.get("http://host/firmware.bin", stream=True,
                    timeout_ms=120_000)
buffer = bytearray(512)
view = memoryview(buffer)

# Inside your service's handle(now_ms) — one slice per tick:
if handle.done and handle.error is not None:
    report(handle.error)                    # failed mid-transfer
elif handle.response is not None:           # headers are in
    count = handle.read_body_into(view)
    if count:
        flash.write(view[:count])
    elif handle.done:
        finish()                             # 0 after done == end of body
```

The contract:

- `handle.response` is set as soon as the final hop's headers arrive —
  before `handle.done` — so you can branch on `status_code` /
  `headers` first.  Its `body` is `b""` and `streamed` is `True`;
  `.text` / `.json()` raise `HttpError`.
- `handle.read_body_into(buffer)` copies decoded body bytes into your
  buffer and returns the count.  `0` means "nothing this tick"; once
  `handle.done` is `True` (with no `error`), `0` means end of body.
- Backpressure is automatic: when the staging window is full the
  client stops reading the socket (and reports no poll interest, so a
  runner parks instead of spinning) until you drain it.
- `max_body_bytes` and `WhenOversized` do not apply to streamed
  bodies — the staging window is the RAM bound.  To enforce your own
  ceiling, count what you read and call `client.cancel()`.
- `timeout_ms` covers the whole transfer, your reads included — size
  it for the download, not the round-trip.
- `client.cancel()` aborts the request immediately (the handle fails
  with `HttpError`), for early exits that shouldn't wait out the
  timeout.

The generator form wraps the same machinery, one chunk per
`yield from`:

```python
from chumicro_requests.generators import stream

def download(transport_factory, url, sink):
    reader = yield from stream(transport_factory, "GET", url,
                               timeout_ms=120_000)
    if reader.response.status_code != 200:
        reader.cancel()
        return
    buffer = bytearray(512)
    view = memoryview(buffer)
    while True:
        count = yield from reader.read_into(view)
        if count == 0:
            break
        sink(view[:count])

runner.add_generator(download(transport_factory, url, flash.write))
```

## Body decoding

`Response.body` is always raw `bytes`.  `Response.text` decodes those
bytes using `Response.encoding`, which is sniffed from the
`Content-Type` header's `charset=` parameter (default `utf-8`).
Override the encoding when a server's Content-Type lies:

```python
response = handle.result
response.encoding = "latin-1"
print(response.text)
```

`Response.json()` decodes via `text` first, then runs `json.loads`,
so charset overrides apply to JSON responses too.

The `transport_factory` argument is a callable
`(host, port, use_tls) -> SocketConnector` — a tick-driven connector,
not a ready socket (see [Bring your own transport](#bring-your-own-transport)
below for the connector contract). The bundled
`chumicro_sockets.sockets_factory.connector_factory(radio=..., ssl_context=...)`
returns one wired to `chumicro-sockets`. The helper lives in an opt-in
submodule so users with a custom transport never trigger the
`chumicro-sockets` deploy. Tests pass a factory returning a
`chumicro_sockets.testing.FakeSocketConnector` (which wraps a
`FakeSocket`).

## Bring your own transport

`HttpClient` does not care which library produces its sockets.  The `transport_factory` you pass is a callable of shape `(host: str, port: int, use_tls: bool) -> SocketConnector`.  The connector advances the TCP connect one tick at a time, but the DNS lookup and, on MicroPython / CircuitPython, the TLS handshake block the reactor for their duration — on a slow or unreachable host that can be seconds, freezing every other runner service, so connect before starting time-critical work.  Once `connector.state == "ready"`, the underlying socket must expose the four-method contract:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data, returns 0 on peer-close, otherwise returns bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns bytes sent (may be partial). |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

`chumicro_sockets.connector` is one producer.  See `chumicro_sockets._connector.SocketConnector` for the connector contract (`tick(now_ms)`, `state`, `socket`, `io_*`, `next_deadline`, `cancel`) — any tick-driven state machine with that surface works as a custom factory.

If you supply your own factory and want `chumicro_sockets` dropped from the deploy, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

The constant accepts a family form (the bare stem, matches every `chumicro_*.sockets_factory`) or an exact dotted path (`chumicro_sockets.sockets_factory`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `HttpClient.from_config(...)` when `chumicro_sockets.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwarg.

For the full single-library adoption recipe — your transport, your `ticks=`, the runner-less drive loop, and host tests with no board — see [Standalone integration](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/standalone-integration.md).

## Runner pattern

`HttpClient.check(now_ms) -> bool` and `handle(now_ms) -> None` satisfy the
runner contract. Drop the client into a `Runner` alongside an
LED-heartbeat task:

```python
from chumicro_runner import Runner
from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory

http_client = HttpClient(transport_factory=connector_factory(radio=radio))
runner = Runner([http_client, blink_task])
while True:
    runner.tick(ticks_ms())
```

## Memory notes

The default 64 KB `max_body_bytes` cap is sized for the minimum
supported board class (256 KB MCU RAM). Bump it for larger boards if needed; the `Response.body`
buffer grows up to that cap. The default 1024-byte `recv_budget_per_tick`
matches `chumicro-mqtt`'s — bytes drained per tick are bounded so concurrent
runner tasks (LED blink, control loop) keep getting CPU time even mid-large-body.
For bodies that shouldn't (or can't) sit in RAM at all, use
`stream=True` — see [Streaming large bodies](#streaming-large-bodies):
the per-request cost drops to the `stream_buffer_size` staging window
(default 1024 bytes) regardless of body size.

## Platform notes

Pure Python, no third-party deps beyond `chumicro-sockets` and `chumicro-timing`.
Works identically on CPython, MicroPython, and CircuitPython once the
connection factory is wired up. HTTPS uses the same
`chumicro_sockets.sockets_factory.connector_factory(ssl_context=...)`
pattern as plain HTTP.

### HTTPS heap headroom on minimum-class boards

mbedTLS handshake costs heap — bench-tested on Pi Pico W MP with a
raw-stdlib `ssl.wrap_socket()` against `letsencrypt.org:443`, the
handshake consumed about 25 KB of heap on top of whatever the app
already had loaded.  Headroom matters: an app that's loaded a lot
into RAM (chumicro stack + workspace fixtures + per-example helpers)
can run the handshake out of memory and surface as `OSError(12)`
(ENOMEM) inside `wrap_socket()`.  If you see ENOMEM on HTTPS, the
two levers are (a) drop unused imports before the request, or (b)
switch to flash deploy mode (chumicro-deploy `--mode flash`) so the
library bootstrap lives on flash and the heap is free for the
handshake.

### TLS context — bring your own CA

`chumicro_sockets.sockets_factory.connector_factory(ssl_context=...)`
accepts an SSL context built via `chumicro_sockets.ssl_context_with_ca(pem)`.
CA-pinning is required
on both supported embedded runtimes — but for different reasons:

- **MicroPython** doesn't have `ssl.create_default_context()` at all;
  every TLS context must be built explicitly.
- **CircuitPython** has `ssl.create_default_context()` (and it builds
  cheaply — ~80 bytes of heap on a Pi Pico W), but the returned context
  carries no CAs and has `check_hostname=False` — handshake against any
  real cert would fail.

So on both runtimes, pass a context with a CA loaded. The CPython "default
context loads a 100-200 KB system trust store" intuition doesn't apply —
neither MP nor CP bundles a trust store, by design.

### Device RTC must be set before TLS

mbedTLS `CERT_REQUIRED` checks the cert validity window against the device
clock. A board with no RTC battery and no NTP boots at 2021-01-01 (or epoch),
which is "before" every modern cert's `not_valid_before` field — handshake
fails with `ValueError("certificate validity starts in the future")`.
Use [`chumicro-ntp`](https://chumicro.github.io/ChuMicro/ntp/stable/) to set the device clock from a public NTP server before the TLS handshake.  Cross-runtime, non-blocking, takes a UDP socket you provide.

## Examples

| Example | What it shows |
|---|---|
| `periodic_get.py` | Periodic GET on a real CP/MP board — wifi up, hits a configured URL every N seconds, drives an LED-blink counter to verify the request never blocks the loop.  Cross-runtime (CP + MP). |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
