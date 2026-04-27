# Decision 0041: chumicro-http-server — runner-shaped HTTP server

Status: `accepted`
Date: `2026-04-26`
Related: [Decision 0014](0014-tick-based-runner.md) (runner pattern), [Decision 0031](0031-chumicro-sockets.md) (transport substrate), [Decision 0040](0040-chumicro-requests.md) (sibling client library), `plans/workstreams/beginner-onramp.md` Step 7.

## Context

Step 7 of the beginner-onramp workstream needs an HTTP server so demos
can do useful things — a sensor thing posts readings, a display thing
serves a status page, a board acts as a tiny web-config endpoint.

A 2026-04-26 survey of the established MP/CP HTTP server libraries
(`adafruit_httpserver`, `microdot`, `tinyweb`, `picoweb`) confirmed
nobody does **cooperative non-blocking** server-side.  Adafruit blocks
on `recv_into` per-connection until the request completes or
`socket_timeout` fires (default 1 s — visible LED stutter).  microdot
and tinyweb are asyncio-bound, which doesn't compose with our tick
runner.  picoweb is async too.

The genuine gap `chumicro-http-server` fills: a runner-shaped server
where each connection is a state machine advanced one chunk per
`server.handle(now_ms)` tick, so an LED can keep blinking through a
slow upload, a stalled client, or a chunked POST.  Same architecture
as `chumicro-mqtt` and `chumicro-requests`, sized for Pi Pico W class
boards.

## Decision

### 1. Runner-shaped, per-connection state machine

```python
from chumicro_http_server import HttpServer
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms

server = HttpServer(listener_factory=lambda: tcp_listening_socket(
    host="0.0.0.0", port=8080, radio=wifi.radio,
))

@server.route("/", methods=["GET"])
def index(request):
    return server.respond(200, text="Hello, world!")

@server.route("/sensor", methods=["POST"])
def sensor(request):
    payload = request.json()
    return server.respond(201, json={"received": payload})

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
```

`HttpServer.check` / `handle` are the runner contract — identical
shape to `MQTTClient` and `HttpClient`.  The server holds a bounded
list of in-flight `_Connection` state machines (default 4).  Each
tick: try `accept()` if there's room; advance every in-flight
connection by one budgeted slice of work.

### 2. Per-connection state machine

```
WANT_REQUEST_LINE
  -> WANT_HEADERS
    -> DISPATCHING            (handler runs synchronously here)
      -> WANT_SEND_HEADERS
        -> WANT_SEND_BODY
          -> DONE / CLOSING
                       \-> ERROR (any state)
```

Handler is called once, after headers parse, **before** the body is
consumed.  The handler may reject without reading the body (saves
bandwidth on 404 / 401 / 405).  When the handler wants the body it
calls `request.body_bytes(max_bytes=...)` or `request.json()` — the
runner advances the body parser across ticks until the body is
buffered, then re-enters the handler's continuation.  v1 keeps the
handler interface synchronous-feeling: handler returns a `Response`
object directly, body parsing happens via the same call-and-resume
trick the runner already uses for the response writer.

(Streaming request bodies — handler pulls one chunk per tick — are a
v2 ask.  v1 buffers up to `max_request_body_bytes` per request.)

### 3. Two-dict router

Borrowed from tinyweb (`server.py:400-419`).  No regex on the device
by default — regex objects burn 200-400 bytes each on MP, and 20
routes is real RAM.

```python
self._explicit_routes: dict[(method, path), handler]   # O(1) full-path
self._pattern_routes: list[(method, prefix, param_name, handler)]  # /users/<id>
```

The decorator `@server.route("/users/<id>", methods=["GET"])` parses
the path at registration time: any segment matching `<name>` becomes
a single trailing parameter (limit: one parameter per path).  Multi-
parameter routes + regex are an opt-in v2 (the registration site
takes a precompiled `re` object instead of a string).

### 4. Per-tick budgets

| Knob | Default | Why |
|------|---------|-----|
| `max_connections` | 4 | Pi Pico W heap can hold ~4 mid-pipeline conn states (~2 KB each + buffers).  Caller can lower to 1 for tight environments. |
| `request_timeout_ms` | 10 000 | Per-connection deadline.  Connection that hasn't reached `DONE` is dropped + socket closed. |
| `recv_budget_per_tick` | 1024 (per conn) | Same as `chumicro-mqtt` / `chumicro-requests`.  Bounds tick latency. |
| `send_budget_per_tick` | 4096 (per conn) | Higher than recv because outbound is typically a 200 OK with a 50-byte JSON; we want to drain it in one tick when possible. |
| `max_request_body_bytes` | 16 384 | Cap on a single buffered request body.  16 KB is a reasonable IoT payload ceiling. |
| `accept_per_tick` | 1 | Avoid burst-accepting 4 conns in one tick — spread them out so the runner can interleave. |

### 5. Reuses from `chumicro-requests`

The wire format primitives we built for the client are exactly what
the server-side parser needs.  `chumicro-http-server` depends on
`chumicro-requests` for:

* `CaseInsensitiveDict` — header dict shape
* `parse_charset` — Content-Type charset sniff
* The chunked-decoder state-machine pattern (lifted into a
  `_RequestBodyParser` analogous to `ResponseParser`)
* `HttpError` / `HttpProtocolError` / `HttpURLError` exception
  hierarchy (re-exported as `ServerError` etc. for caller-facing
  ergonomics)

This couples server → requests, which is mildly weird (server
depending on the client library).  The pragmatic alternative — extract
the shared primitives into a `chumicro-http` library — is real work
across already-shipped v1 surface and is deferred until a third
consumer surfaces (matches the `WhenOversized` precedent).

### 6. Listener factory + new `chumicro-sockets` helper

```python
listener_factory: Callable[[], ListeningSocket]
```

Where `ListeningSocket` exposes:

```python
def accept(self) -> tuple[TCPClientSocket, tuple[str, int]] | None
def close(self) -> None
def fileno(self) -> int
```

`accept()` returns `None` (or raises EAGAIN) when no pending
connection is queued, **never blocks**.  `chumicro-sockets` 0.1.6
ships a `tcp_listening_socket(host, port, *, backlog=4, radio=None)`
helper that opens a non-blocking listener via the runtime-appropriate
adapter (CP `socketpool.SocketPool.socket().bind().listen()`, MP
`socket.socket().bind().listen()`, CPython stdlib).  The returned
socket's `accept()` returns a `(TCPClientSocket, address)` tuple
that the server adds to its in-flight list.

### 7. Response API

```python
def respond(
    status: int = 200,
    *,
    body: bytes | str | None = None,
    json: object | None = None,
    text: str | None = None,
    html: str | None = None,
    headers: object | None = None,
) -> Response: ...
```

Mutually exclusive: pass at most one of `body` / `json` / `text` /
`html`.  `text` defaults `Content-Type: text/plain; charset=utf-8`.
`html` defaults `text/html; charset=utf-8`.  `json` runs `json.dumps`
+ sets `application/json`.  `body` is raw bytes pass-through.
Caller `headers=` overrides the defaults.

### 8. TLS server — supported on MicroPython, blocked on CircuitPython

Slice 7t investigation (2026-04-26) actually verified TLS server
on a Pi Pico W class board.  Adafruit's "limited support for
HTTPS (only on selected microcontrollers with enough memory e.g.
ESP32-S3)" framing turned out to be too pessimistic — the heap
budget on Pi Pico W MicroPython is fine.  CircuitPython is the
real blocker, for a different reason.

**Live measurements on Pi Pico W MicroPython 1.28.0 (rp2 port):**
* SSLContext build cost (RSA-2048 cert + key, DER-encoded):
  ~8 KB heap.
* Per-connection handshake cost: ~25 KB heap.
* Free heap remaining post-handshake: ~130 KB.
* Result: full HTTPS GET round-trip succeeded, response delivered.
  See ``.scratch/run_tls_server_probe.py``.

**CircuitPython 10.2.0-rc.0 — server-side TLS works on ESP32-S2 / S3
via the path-based cert API.**

Initially I claimed CP TLS server was blocked by
missing ``PROTOCOL_TLS_SERVER``; that was wrong (the user
correctly pushed back).  CP exposes only ``SSLContext`` and
``create_default_context`` at module level — no ``PROTOCOL_*``
constants, no ``Purpose`` enum — but adafruit_httpserver's HTTPS
path **does** work, because:

```python
ctx = ssl.create_default_context()       # nominally client-side
ctx.load_verify_locations(cadata="")     # required pre-load step
ctx.load_cert_chain(cert_path, key_path) # paths, not bytes
sock = ctx.wrap_socket(sock, server_side=True)  # works anyway
```

The only gotcha vs the in-memory bytes path the MP / CPython
adapters use: CP's ``load_cert_chain`` requires *filesystem
paths* (it raises ``OSError(2)`` on bytes, treating them as a
path it can't open).  Cross-runtime API:
:func:`chumicro_sockets.ssl_context_with_cert_and_key_paths`
(works everywhere) vs
:func:`ssl_context_with_cert_and_key` (bytes; CP raises clear
error pointing to the path-based helper).

**Live measurements on Lolin S2 (ESP32-S2) / CP 10.2.0-rc.0:**

* SSLContext build + cert load: ~6 KB heap.
* Per-connection handshake cost: ~35 KB heap.
* Free heap remaining post-handshake: ~1.99 MB.
* End-to-end: HTTPS GET round-trip from a host CPython client
  to the device handshakes + delivers response.

**Pi Pico W (rp2) / CP 10.2.0-rc.0 — fails post-handshake** with
``OSError(32)`` (EPIPE) on the server-side ``accept()`` after the
TLS handshake completes.  Heap was 115 KB free at the time, so
not a memory issue — likely an rp2-port mbedTLS feature-flag
problem.  Filed as a follow-up; the ESP32 family is the
recommended Pi Pico W alternative for HTTPS server use cases on
CircuitPython today.

Adafruit's "ESP32-S3 only" framing in the ``httpserver`` README
overstates the constraint — verified ESP32-S2 also works.  S3 +
larger boards work fine; rp2 has a port-specific issue.

**Shipping policy:**
* `chumicro_sockets.tls_listening_socket(...)` works on MicroPython
  + CPython; raises `UnsupportedSSLConfigError` with a clear message
  on CircuitPython.
* `chumicro_sockets.ssl_context_with_cert_and_key(cert_pem, key_pem)`
  works on MP + CPython; raises `UnsupportedSSLConfigError` on CP.
* For HTTPS on CircuitPython boards, the workaround is unchanged
  from the surveyed prior art: terminate TLS in front of the board
  with a proxy (Caddy / nginx / Cloudflare Tunnel) and let the
  board speak plain HTTP on the LAN behind it.

**Other v1 non-goals (unchanged):**
* **WebSockets / SSE.**  Connection-upgrade dance + long-lived
  framing are big enough to deserve their own library.
* **Sessions / cookies / auth helpers.**  Caller sets a `Set-Cookie`
  header manually if they want one; no jar.  Basic / bearer / token
  auth helpers can live in a sibling `chumicro-http-server-auth`
  package later.
* **Multipart form parsing.**  v1 supports JSON + raw body + URL
  query parameters.  Multipart upload is rare on these boards and
  expensive to parse.
* **Static file serving from a directory tree.**  v1 serves files
  one-handler-at-a-time via `respond(body=open(...).read())` or a
  small `serve_file(path)` helper.  Directory-walking + MIME-type
  database is deferred — Adafruit ships a 200-line MIME map that
  most users don't need.
* **Reverse proxy / sub-app mounting** (microdot's `mount`,
  picoweb's tree-walk).  One server, one route table.
* **Async handlers.**  Synchronous handler-returns-Response.  v2
  could add a `handler(request, respond)` shape that lets a slow
  handler yield back to the runner mid-response.

## Consequences

* New device library `libraries/http_server/` ships pure-Python
  source compatible with all three runtimes.  Depends on
  `chumicro-sockets` (transport + new listener) + `chumicro-timing`
  (ticks) + `chumicro-requests` (wire-format primitives).  Optional
  `chumicro-runner` hook: `HttpServer` satisfies `check(now_ms) ->
  bool` so `Runner` can drive it directly.
* `chumicro-sockets` 0.1.6 adds `tcp_listening_socket` per-runtime.
  The chumicro-sockets package picks up server-side concerns for
  the first time — kept narrow (no TLS server, no UDP, no SOCKS).
* The two-thing demo (Step 8) becomes writable: a sensor thing
  POSTs JSON to a server thing's `/sensor` endpoint over LAN.
  Both run on Pi Pico W class boards.
* Implementation phases in slices, each green-preflight + commit:
  * **7a** — `chumicro-sockets` listener + `HttpServer` accept
    loop + request line + header parser + canned 200 response.
    Single connection at a time.
  * **7b** — Two-dict router + decorator + per-route dispatch +
    `respond()` helpers (text / html / json / body).
    `request.json()`, `request.query`, `request.path_params`.
  * **7c** — Bounded multi-connection (`max_connections` >= 1);
    per-tick budgets; `request_timeout_ms`.
  * **7d** — Live-board verification on Pi Pico W (CP + MP).
* Decision 0040's "extract shared HTTP wire primitives" follow-up
  becomes more concrete — server reuses `CaseInsensitiveDict` /
  `parse_charset` / chunked decoder.  When a third consumer
  surfaces (e.g. `chumicro-websocket`) we extract to a
  `chumicro-http` library.  Until then, server depends on requests.
