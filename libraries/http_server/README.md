# chumicro-http-server

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A non-blocking HTTP/1.1 server with `@route` — serve requests while your LED keeps blinking.**

Routing with `@server.route` (method dispatch, path parameters), bounded multi-connection, per-tick byte budgets, and a streaming request parser — all without blocking your main loop.  Serves TLS on every supported board pair except CircuitPython on RP2040 (CYW43 substrate limitation; documented inline).  Self-contained — no `chumicro-requests` dependency on the device.

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
| `ServerError` + subclasses | Typed exception hierarchy, independent of `chumicro_requests` so the server can ship without the client library. |

Each request is served on a fresh accepted socket and `Connection: close` is added to every response — HTTP/1.1 keep-alive and connection pooling are not supported.  Chunked request bodies are not supported either; use `Content-Length`.

## Where this fits

Depends on [`chumicro-sockets`](../sockets/) (TCP listener) and [`chumicro-timing`](../timing/) (ticks).  Pairs with [`chumicro-websockets`](../websockets/) for combined HTTP + WS deployments.  Self-contained otherwise — the shared HTTP/1.1 primitives (case-insensitive header dict, charset parsing) are inlined locally, so a server-only board never ships [`chumicro-requests`](../requests/).

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Pure Python — no native extensions.

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
| `simple_server.py` | Single-board HTTP server with `GET /`, `GET /api/uptime`, `POST /api/echo` routes.  Drive it with `curl` from your laptop.  Cross-runtime (CP + MP) — runtime marker on the file gates hardware-only deploys.  For a two-physical-board demo see the workspace template's `two_board_handshake/` example. |

## Wiring wifi credentials for examples and functional tests

The hardware-prefixed examples + real-network suites in `functional_tests/test_real_*.py` need wifi credentials.  See [`docs/wiring-wifi-credentials.md`](https://github.com/ChuMicro/ChuMicro/blob/main/docs/wiring-wifi-credentials.md) for the workspace-based and raw single-file paths.  The library itself never reads TOML — it takes a `listener_factory` and goes; config wiring is application-layer.

## Contributing

Working on `chumicro-http-server` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/http-server/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/http-server/experimental/)**

## Find this library

- **PyPI:** [chumicro-http-server](https://pypi.org/project/chumicro-http-server/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_http_server) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_http_server)
- **Source:** [libraries/http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
