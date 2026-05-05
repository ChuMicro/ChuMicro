# chumicro-http-server

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.
Built on `chumicro-sockets` (TCP listener) and `chumicro-timing` (ticks).
Each connection is a state machine advanced one chunk per runner tick —
an LED keeps blinking while requests are being served.  Self-contained
(no `chumicro-requests` dep) so a server-only board only ships server
code.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-http-server

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_http_server

# CPython
pip install chumicro-http-server
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms

server = HttpServer(
    listener_factory=lambda: tcp_listening_socket(host="0.0.0.0", port=8080),
)

@server.route("/")
def index(request):
    return build_response(200, html="<h1>Hello from a Pi Pico W</h1>")

@server.route("/sensor", methods=["POST"])
def sensor(request):
    payload = request.json()
    return build_response(201, json={"ok": True})

@server.route("/widgets/<id>")
def widget(request):
    return build_response(200, json={"id": request.path_params["id"]})

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
```

## What's included

| Symbol | Purpose |
|---|---|
| `HttpServer` | Runner-shaped HTTP/1.1 server; `check(now_ms)` / `handle(now_ms)`. |
| `Request` | Per-request value object: `method`, `path`, `query`, `headers`, `body`, `json()`, `text()`. |
| `Response` | Outbound response: `status_code`, `reason`, `headers`, `body`. |
| `build_response(status, *, body, json, text, html, headers)` | Convenience builder with sensible Content-Type defaults. |
| `RequestParser` | Streaming request parser (request line + headers + Content-Length body). |
| `parse_query` / `split_target` | URL helpers. |
| `ServerError` + subclasses | Typed exception hierarchy (subclasses `chumicro_requests.HttpError`). |

v1 ships end-to-end: listener + parser + canned response,
`@server.route` decorator + JSON helpers + multi-method dispatch,
bounded multi-connection + per-tick budgets + `request_timeout_ms`,
and live-board verification on Pi Pico W.

v1 non-goals: WebSockets, sessions / cookies / auth helpers, multipart
upload, sub-app mounting, async handlers.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Pure Python; depends
only on `chumicro-sockets` and `chumicro-timing`.  The shared HTTP/1.1
primitives (case-insensitive header dict, charset parsing) are inlined
locally — no `chumicro-requests` dependency on the device.

### TLS server (HTTPS)

`chumicro-http-server` itself is transport-agnostic — pass a TLS-wrapped
listener from
[`chumicro_sockets.ssl_context_with_cert_and_key_paths`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets)
into `listener_factory` and the same `HttpServer` runs HTTPS.  Live
verification across the supported board matrix:

| Runtime + board | TLS server status | Notes |
|---|---|---|
| CircuitPython on ESP32-S2 (Lolin S2) | ✅ Works | ~6 KB context + ~35 KB handshake heap. |
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) | ❌ Refused (`UnsupportedSSLConfigError`) | `chumicro_sockets.tls_listening_socket` raises up-front; the underlying CYW43 TLS path raises `OSError(32)` mid-handshake AND wedges the chip's station-mode state. Use ESP32-family or MicroPython on rp2. |
| MicroPython on ESP32-S2 | ✅ Works | Hardware-accelerated handshake; ~1 KB heap. |
| MicroPython on rp2 (Pi Pico W) | ✅ Works (RSA-2048 only) | DER-encoded key; ~25 KB handshake heap; ECC keys fail at context build. |

> **Why the CP-on-rp2 row?**  The CYW43 stack's TLS server path raises `OSError(32)` mid-handshake and wedges the chip's station state until a USB power-cycle.  No upstream fix is in flight; for HTTPS server work on rp2, use MicroPython.

The TLS handshake is synchronous inside `wrap_socket(..., server_side=True)`;
budget for a ~100–500 ms listener stall during accept.  Once the
handshake completes, the per-connection state machine resumes its
runner-shaped, LED-blink-friendly progression.

## Examples

| Example | What it shows |
|---|---|
| `quickstart.py` | One-shot HTTP request/response over an in-memory `FakeSocket` — runs on any host without a network. |
| `circuitpython_two_thing_server.py` | Display half of a two-thing demo: HTTP server with `GET /`, `GET /api/latest`, `POST /api/sensor` routes; in-memory latest-reading state.  Runs on CP / MP boards (filename prefix marks it hardware-only). |
| `circuitpython_two_thing_sensor.py` | Sensor half of the two-thing demo: posts a synthetic reading to the server every 5 s using `chumicro-requests`. |

## Configuring wifi for examples and functional tests

Real-network functional tests in `functional_tests/test_real_*.py` and the hardware-prefixed examples in `examples/circuitpython_*.py` need wifi credentials.  Two paths, depending on whether you're using a `chumicro-workspace`:

* **With a workspace (recommended).**  Put wifi creds in your workspace's gitignored `workspace.yml`, run `chumicro-workspace deploy --thing <name>`, and the example reads them via `chumicro_config.load_runtime_config()`.  The two-thing demo's `runtime_config` schema also accepts `[two_thing_sensor]` for the sensor's target server overrides — see the example file for keys.
* **Raw single-file deploy** (no workspace).  Edit the `WIFI_SSID` / `WIFI_PASSWORD` constants (and `SERVER_HOST` on the sensor side) near the top of the example file before copying it to `/code.py` (CP) or `/main.py` (MP).  The constants are the fallback when no `runtime_config.msgpack` is present.

The library itself never reads either source — it takes a `listener_factory` and goes.  The config wiring is application-layer.

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
pip install -e .[test]
pytest tests/
pytest functional_tests/   # needs a registered board in devices.yml
```

Before running functional tests, register a board with `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/http-server/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/http-server/experimental/)**

## Find this library

- **PyPI:** [chumicro-http-server](https://pypi.org/project/chumicro-http-server/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_http_server)
- **Source:** [libraries/http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server)
