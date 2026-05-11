# User Guide

## Overview

`chumicro-requests` is a non-blocking HTTP/1.1 client built on `chumicro-sockets`.  `HttpClient` is the single entry point for every verb — its `check(now_ms)` / `handle(now_ms)` methods drive the request forward one tick at a time.  An LED keeps blinking on the same board while a request is in flight, in a TLS handshake, or mid-timeout against a stalled peer.  The library is single-in-flight today — a second `client.get(...)` while another request is running raises `HttpBusyError`.

## Getting started

```python
from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_timing import ticks_ms

client = HttpClient(connection_factory=chumicro_sockets_factory(radio=wifi.radio))
handle = client.get("http://api.example.com/now", timeout_ms=5000)

while not handle.done:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())

response = handle.result
print(response.status_code, response.body)
print(response.text)               # decoded str
print(response.json())             # parsed JSON
```

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
client = HttpClient(connection_factory=..., default_max_redirects=10)
```

Method handling follows long-standing browser + RFC 7231 §6.4 rules:

- `301` / `302` / `303` switch the next hop to **GET with no body**
- `307` / `308` **preserve** the original method and body

`response.url` reflects the URL of the FINAL hop, not the original
request. If the budget is exhausted before reaching a non-3xx response,
the last 3xx is returned to the caller (matching CPython `requests`'
default behaviour without the `raise_for_status()` step).

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

The `connection_factory` argument is a callable
`(host, port, use_tls) -> TCPClientSocket`. The bundled
`chumicro_sockets_factory(radio=..., ssl_context=...)` returns one wired to
`chumicro-sockets`. Tests typically pass a hand-rolled factory that returns a
`chumicro_sockets.testing.FakeSocket`.

## Runner pattern

`HttpClient.check(now_ms) -> bool` and `handle(now_ms) -> None` satisfy the
runner contract. Drop the client into a `Runner` alongside an
LED-heartbeat task:

```python
from chumicro_runner import Runner
from chumicro_requests import HttpClient, chumicro_sockets_factory

http_client = HttpClient(connection_factory=chumicro_sockets_factory(radio=radio))
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

## Platform notes

Pure Python, no third-party deps beyond `chumicro-sockets` and `chumicro-timing`.
Works identically on CPython, MicroPython, and CircuitPython once the
connection factory is wired up. HTTPS uses the same
`chumicro_sockets_factory(ssl_context=...)` pattern as plain HTTP.

### HTTPS on Pi Pico W class boards

The wifi → sockets → TLS → requests stack only fits on the minimum
supported board class (256 KB MCU RAM) in **flash deploy mode**. RAM-mode
keeps the entire library bootstrap on the heap for the duration of the
test, leaving < 50 KB for mbedTLS handshake — `ssl_context.wrap_socket(...)`
then fails with `OSError(12)` (ENOMEM). Larger-heap boards (ESP32-S3 with
> 200 KB free heap after wifi) can run HTTPS in RAM-mode; smaller-heap
boards in the supported class (Pi Pico W, Lolin S2 / ESP32-S2 family) need
flash-mode for HTTPS specifically.

### TLS context — bring your own CA

`chumicro_sockets_factory(ssl_context=...)` accepts an SSL context built
via `chumicro_sockets.ssl_context_with_ca(pem)`. CA-pinning is required
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
