# User Guide

## Overview

`chumicro-requests` is a non-blocking HTTP/1.1 client built on `chumicro-sockets`.  `HttpClient` is the single entry point for every verb — its `check(now_ms)` / `handle(now_ms)` methods drive the request forward one tick at a time.  An LED keeps blinking on the same board while a request is in flight, in a TLS handshake, or mid-timeout against a stalled peer.  The library is single-in-flight today — a second `client.get(...)` while another request is running raises `HttpBusyError`.

## Getting started

```python
from chumicro_requests import HttpClient
from chumicro_requests.sockets_factory import chumicro_sockets_factory
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
`chumicro_requests.sockets_factory.chumicro_sockets_factory(radio=..., ssl_context=...)`
returns one wired to `chumicro-sockets`. The helper lives in an opt-in
submodule so users with a custom transport never trigger the
`chumicro-sockets` deploy. Tests typically pass a hand-rolled factory
that returns a `chumicro_sockets.testing.FakeSocket`.

## Bring your own transport

`HttpClient` does not care which library produces its sockets.  The `connection_factory` you pass is a callable of shape `(host: str, port: int, use_tls: bool) -> socket` that returns any object exposing the four-method contract:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data, returns 0 on peer-close, otherwise returns bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns bytes sent (may be partial). |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

`chumicro_sockets.tcp_client_socket` / `tls_client_socket` is one producer.  Stdlib `socket.socket` after `setblocking(False)` is another.  Hand-rolled wrappers around any upstream library work the same way:

```python
import socket as stdlib_socket

def make_connection(host, port, use_tls):
    sock = stdlib_socket.socket(stdlib_socket.AF_INET, stdlib_socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.setblocking(False)
    return sock  # use_tls handled by caller's wrapper if needed

client = HttpClient(connection_factory=make_connection)
```

If you supply your own factory and want `chumicro_sockets` dropped from the deploy, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

The constant accepts a family form (the bare stem, matches every `chumicro_*.sockets_factory`) or an exact dotted path (`chumicro_requests.sockets_factory`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `HttpClient.from_config(...)` when `chumicro_requests.sockets_factory` is missing — either skipped at deploy time or not installed by `circup` / `mip` — raises `RuntimeError` naming the bypass kwarg.

## Runner pattern

`HttpClient.check(now_ms) -> bool` and `handle(now_ms) -> None` satisfy the
runner contract. Drop the client into a `Runner` alongside an
LED-heartbeat task:

```python
from chumicro_runner import Runner
from chumicro_requests import HttpClient
from chumicro_requests.sockets_factory import chumicro_sockets_factory

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
`chumicro_requests.sockets_factory.chumicro_sockets_factory(ssl_context=...)`
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

`chumicro_requests.sockets_factory.chumicro_sockets_factory(ssl_context=...)`
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
