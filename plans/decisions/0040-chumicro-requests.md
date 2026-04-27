# Decision 0040: chumicro-requests — runner-shaped HTTP client

Status: `accepted`
Date: `2026-04-26`
Related: [Decision 0014](0014-tick-based-runner.md) (runner pattern), [Decision 0031](0031-chumicro-sockets.md) (transport substrate), `plans/workstreams/beginner-onramp.md` Step 6.

## Context

The beginner on-ramp workstream needs an HTTP client so demos can do useful
things (fetch weather, ping APIs, talk to local servers).  The closest
reference on CircuitPython is `adafruit_requests`, whose `Session.get(url)`
is **synchronous and blocks** the caller through DNS, TCP connect, TLS
handshake, send, and recv.  On a single-threaded MCU that means every
runner task — LED blink, control loop, sensor sample — stops until the
HTTP call returns.  The whole point of this workspace's runner pattern
(Decision 0014) is that nothing blocks.  An LED has to keep blinking
through a slow request, a TLS handshake, a stalled server, and a
five-second timeout.

`chumicro-mqtt` already proved the runner-shaped contract on top of
`chumicro-sockets`: long-lived client object, `check(now_ms) -> bool`
+ `handle(now_ms)`, per-tick budgets, pre-allocated buffers.  We mirror
that shape here.

## Decision

### 1. Runner-shaped, single-in-flight `HttpClient`

```python
from chumicro_requests import HttpClient, chumicro_sockets_factory

client = HttpClient(connection_factory=chumicro_sockets_factory(radio=wifi.radio))
request = client.get("http://api.example.com/v1/now", timeout_ms=5000)

while not request.done:
    if client.check(now_ms()):
        client.handle(now_ms())

response = request.result          # raises HttpError on failure
print(response.status_code)        # 200
print(response.headers["content-type"])
```

`HttpClient.check` / `handle` are the runner contract — identical shape
to `MQTTClient`.  The client owns one in-flight request at a time;
`client.get(...)` while `client.busy` raises `HttpBusyError` (mirrors
`MQTTBackpressureError`).  Multi-in-flight is **not** in v1 — a 256 KB
MCU mid-TLS-handshake on two sockets is a pathological case we'd
rather not enable by default.  v2 can add bounded queueing if asked.

### 2. Connection factory, not embedded transport

```python
def connection_factory(host: str, port: int, use_tls: bool) -> TCPClientSocket: ...
```

Injected at construction.  The library never imports `chumicro_sockets`
directly in `__init__` so it can be unit-tested with `FakeSocket` without
the real transport.  A convenience helper `chumicro_sockets_factory(*,
radio=None, ssl_context=None)` returns the factory wired to
`chumicro_sockets.tcp_client_socket` / `tls_client_socket` — the
default consumer path on a board.

### 3. Per-request budgets capped for tick safety

| Knob | Default | Why |
|------|---------|-----|
| `timeout_ms` | 10 000 | Total per-request deadline (DNS → connect → handshake → response). |
| `max_body_bytes` | 65 536 (64 KB) | Cap the buffered response.  Decision 0015 minimum board class is 256 KB MCU RAM — a 64 KB body leaves headroom. |
| `max_redirects` | 5 | Per request.  Slice 3e wires this in. |
| `recv_budget_per_tick` | 1024 | Client-level (mirrors `MQTTClient.recv_budget_per_tick`).  A 64 KB body takes ~64 ticks to drain — the LED keeps blinking. |
| `when_oversized` | `DROP_WITH_EVENT` | Same enum shape as `chumicro_mqtt.WhenOversized`.  Fires `client.on_oversized(url, reported_length)`. |

### 4. Headers are case-insensitive

`Response.headers` is a thin case-insensitive `dict`-like (lookups
fold to lower) — pre-allocated, no third-party dependency.  Header
*ordering* on send isn't preserved (HTTP/1.1 doesn't require it).
Multi-value headers (e.g. `Set-Cookie`) join with `, ` per RFC 7230 §3.2.2;
v1 has no cookie jar so the join is information only.

### 5. Body buffering, not streaming

v1 buffers the full response body up to `max_body_bytes`.  Streaming
via callback/iterator is a v2 ask — wait for a real consumer who needs
it.  The cap + the per-tick recv budget together mean a 64 KB cap +
1024-byte tick yields a worst-case 64-tick body drain on a slow link;
not great, but not blocking, and bounded.

### 6. TLS sits on `chumicro-sockets`

No reimplementation.  `connection_factory(host, port, use_tls=True)`
returns whatever socket the factory builds — `chumicro-sockets`'
`tls_client_socket` already handles per-runtime TLS context shaping
(Decision 0031, plus the `CERT_REQUIRED` default fix in 0.1.4).

### 7. v1 non-goals

- **Keep-alive / connection reuse.**  One socket per request.
- **gzip / deflate / brotli.**  Send `Accept-Encoding: identity` by default; require server cooperation.
- **Multipart / form-encoded bodies.**  Slice 3d ships JSON only;
  raw `bytes` / `str` body pass-through covers the rest.
- **Cookies.**  No jar.  Callers can stuff `Cookie:` headers manually if needed.
- **Chunked transfer-encoding *send*.**  Slice 3f decodes inbound
  chunked responses.  Outbound is `Content-Length` only.
- **Authentication helpers** (Basic / Bearer / OAuth).  Caller sets the
  `Authorization` header.
- **Async sugar / sync wrapper.**  Tempting to ship `client.get_sync(url)`
  that spins the runner internally — but the user can't blink an LED
  during that call.  The runner-shaped API stays canonical; sugar is
  rejected for v1.

### 8. Divergence from `adafruit_requests`

| Concern | adafruit_requests | chumicro-requests |
|---------|-------------------|-------------------|
| Programming model | Synchronous; `Session.get()` blocks the caller through every phase. `_readinto` assumes blocking I/O. | Runner-shaped (`check` / `handle`); per-tick recv budget; LED-friendly. |
| TLS | `socket_pool` + `ssl_context` injected into `Session`. | Indirect via `connection_factory` (which itself sits on `chumicro-sockets`). |
| Body | `.content` (full) **and** `.iter_content(chunk_size)` (streaming). | Full-buffer only in v1. |
| Connection reuse | Manager caches sockets per `(host, port)`. | None in v1. |
| EAGAIN handling | `_send` retries; `_readinto` does not. | Both paths handle EAGAIN — must, since both are non-blocking. |

Cited from `adafruit_requests.py` (main branch as of 2026-04-26):
`Session.__init__` ll. ~120, `Session.request` ll. 545–680, `_send`
ll. 559–577, `_readinto` ll. 330–347, `Response.content` l. 374,
`Response.iter_content` ll. 411–427.

## Live-board limitations (slice 3c)

These showed up only on real hardware; they're constraints of the
embedded TLS stack, not of `chumicro-requests` per se.  Documented
here because slice 3c is when they bite.

* **HTTPS requires flash deploy mode on Pi Pico W class boards.**
  RAM-mode keeps the full library bootstrap on the heap and leaves
  < 50 KB for the mbedTLS handshake → `OSError(12)`.  Flash-mode
  bootstraps from disk; ~150 KB free heap available for the
  handshake.  The four-board canonical matrix (Pi Pico W CP/MP,
  Lolin S2 CP/MP) was verified live with `--deploy-mode flash`.
  ESP32-S3 with > 200 KB free heap after wifi can run HTTPS in
  RAM-mode; document and let the user choose.
* **TLS context must be CA-pinned — but for different reasons per
  runtime.**  Probed live on Pi Pico W in flash mode:
    - **MicroPython 1.28.0 / rp2:** `ssl.create_default_context()`
      *doesn't exist* — `AttributeError("'module' object has no
      attribute 'create_default_context'")`.  You must build a
      context yourself via `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`
      or use `chumicro_sockets.ssl_context_with_ca(pem)`.
    - **CircuitPython 10.2.0-rc.0:** `ssl.create_default_context()`
      *does* exist and constructs cheaply (~80 bytes of heap), but
      the returned context has `check_hostname=False` and no CAs
      loaded — handshake against any real cert would fail.  The
      "100-200 KB trust store doesn't fit" intuition from CPython
      doesn't apply: CP simply doesn't bundle a trust store at all.
    - The earlier RAM-mode `MemoryError`/`OSError(12)` symptoms were
      the **mbedTLS handshake itself** OOMing, not the context
      construction.  Flash mode gives the handshake the headroom
      it needs; the context-must-be-CA-pinned rule remains
      independent of deploy mode because both runtimes need
      caller-supplied CAs to verify against.

  Use `chumicro_sockets.ssl_context_with_ca(pem)` on both runtimes —
  it returns a `CERT_REQUIRED` context with the supplied CA
  loaded.  Same pattern Phase 7 TLS-MQTT proved.
* **Device RTC must be set before TLS.**  mbedTLS `CERT_REQUIRED`
  rejects every cert with "validity starts in the future" if the
  RTC is at boot default (2021-01-01 on rp2, epoch elsewhere).
  Caller's responsibility to NTP-sync before issuing HTTPS;
  documented in `docs/guide.md` §Platform notes.

## Consequences

- A new device library, `libraries/requests/`, ships pure-Python source
  compatible with all three runtimes.  Depends on `chumicro-sockets`
  (transport) and `chumicro-timing` (ticks).  Optional `chumicro-runner`
  hook: `HttpClient` satisfies `check(now_ms) -> bool` so `Runner` can
  drive it directly.
- The "fetch weather" demo and the eventual two-thing demo (sensor →
  HTTP server) become writable.  Until slices 3c + 3d land (HTTPS
  + POST/JSON), demos stick to plain-HTTP GET.
- Implementation phases in slices, each green-preflight + commit:
    * **3a** plain HTTP GET against `FakeSocket` — status line + header
      parse, no body decode.
    * **3b** body decode for `Content-Length` responses (bytes + str).
    * **3c** HTTPS via `chumicro-sockets` TLS path.
    * **3d** `POST` + body + `request.json()` / `client.post(..., json=...)`.
    * **3e** redirect following with `max_redirects` budget.
    * **3f** chunked transfer-encoding decode.
- `WhenOversized` enum lives in `chumicro_requests`, parallel to
  `chumicro_mqtt.WhenOversized`.  Tempted to factor a shared one out;
  not yet — copy first, abstract on the third user.
- The single-in-flight constraint may bite users who want to fan
  out N concurrent requests.  Documented; v2 can add a pool if a
  consumer asks.
