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
connection factory is wired up. HTTPS landed in slice 3c (Decision 0040)
with the same `chumicro_sockets_factory(ssl_context=...)` pattern; v1
remaining: POST + JSON helpers, redirects, chunked transfer-encoding
(slices 3d–3f).

### HTTPS on Pi Pico W class boards

The wifi → sockets → TLS → requests stack only fits on the Decision 0015
minimum board class (256 KB MCU RAM) in **flash deploy mode**. RAM-mode
keeps the entire library bootstrap on the heap for the duration of the
test, leaving < 50 KB for mbedTLS handshake — `ssl_context.wrap_socket(...)`
then fails with `OSError(12)` (ENOMEM). Larger-heap boards (ESP32-S3 with
> 200 KB free heap after wifi) can run HTTPS in RAM-mode; the four-board
canonical matrix (Pi Pico W CP/MP, Lolin S2 CP/MP) needs flash-mode for
HTTPS specifically.

### TLS context — bring your own CA

`chumicro_sockets_factory(ssl_context=...)` accepts an SSL context built
via `chumicro_sockets.ssl_context_with_ca(pem)`. Default `ssl.create_default_context()`
on these boards loads ~100-200 KB of bundled trust store and OOMs on a
Pi Pico W. Pin a single CA (or small chain bundle) — the Phase 7 TLS-MQTT
work proved this pattern works.

### Device RTC must be set before TLS

mbedTLS `CERT_REQUIRED` checks the cert validity window against the device
clock. A board with no RTC battery and no NTP boots at 2021-01-01 (or epoch),
which is "before" every modern cert's `not_valid_before` field — handshake
fails with `ValueError("certificate validity starts in the future")`.
Standard fix on MP: `import ntptime; ntptime.settime()` after wifi is up.
On CP: an NTP query over `socketpool` (e.g. `adafruit_ntp`). The chumicro
workspace will eventually bake this into a `chumicro-ntp` library; until
then it's the caller's responsibility.

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
