# User Guide

## Overview

`chumicro-requests` is a non-blocking HTTP/1.1 client built on
`chumicro-sockets`. The canonical entry point is `HttpClient`, a runner-shaped
object whose `check(now_ms)` / `handle(now_ms)` methods drive the request
forward one tick at a time. The LED-blink invariant (Decision 0040): an LED
keeps blinking on the same board while a request is in flight, in a TLS
handshake, or mid-timeout against a stalled peer. The library is single-in-flight
in v1 — a second `client.get(...)` while another request is running raises
`HttpBusyError`.

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
Decision 0014 runner contract. Drop the client into a `Runner` alongside an
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

The default 64 KB `max_body_bytes` cap is sized for Decision 0015 minimum
boards (256 KB MCU RAM). Bump it for larger boards if needed; the `Response.body`
buffer grows up to that cap. The default 1024-byte `recv_budget_per_tick`
matches `chumicro-mqtt`'s — bytes drained per tick are bounded so concurrent
runner tasks (LED blink, control loop) keep getting CPU time even mid-large-body.

## Platform notes

Pure Python, no third-party deps beyond `chumicro-sockets` and `chumicro-timing`.
Works identically on CPython, MicroPython, and CircuitPython once the
connection factory is wired up. HTTPS lands in slice 3c (Decision 0040); v1
slice 3a is plain HTTP only. POST + JSON helpers, redirects, and chunked
transfer-encoding follow in slices 3d–3f.

## Examples

| Example | What it shows |
|---|---|
| `quickstart.py` | Plain HTTP GET against an in-memory `FakeSocket` — runs on any host without a network. |

## What's new

*No changes yet — this section will be updated with each release.*

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
