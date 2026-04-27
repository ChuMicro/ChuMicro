# chumicro-http-server

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.
Built on `chumicro-sockets` (TCP listener) and `chumicro-timing` (ticks),
sharing wire-format primitives with `chumicro-requests`.  Each connection
is a state machine advanced one chunk per runner tick — an LED keeps
blinking while requests are being served.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-http-server
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_http_server
```

### CPython (pip)

```bash
pip install chumicro-http-server
```

## Quick example

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms

def handle_request(request):
    if request.method == "GET" and request.path == "/":
        return build_response(200, html="<h1>Hello from a Pi Pico W</h1>")
    if request.method == "POST" and request.path == "/sensor":
        payload = request.json()
        # ... store the reading ...
        return build_response(201, json={"ok": True})
    return build_response(404, text="not found")

server = HttpServer(
    listener_factory=lambda: tcp_listening_socket(
        host="0.0.0.0", port=8080, radio=wifi.radio,
    ),
    handler=handle_request,
)

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

v1 scope (Decision 0041) ships in slices: 7a — listener + parser +
canned response (this commit); 7b — `@server.route` decorator + JSON
helpers + multi-method dispatch; 7c — bounded multi-connection +
per-tick budgets + request_timeout_ms; 7d — live-board verification
on Pi Pico W.  TLS server is investigated separately.

v1 non-goals: WebSockets, sessions / cookies / auth helpers, multipart
upload, sub-app mounting, async handlers.  See Decision 0041 §8.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Pure Python; depends
only on `chumicro-sockets`, `chumicro-timing`, and `chumicro-requests`
(for shared wire-format primitives — `CaseInsensitiveDict`,
`parse_charset`, exception hierarchy).

## Examples

| Example | What it shows |
|---|---|
| `quickstart.py` | One-shot HTTP request/response over an in-memory `FakeSocket` — runs on any host without a network. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries http_server
```

See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md).

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/http-server/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/http-server/experimental/)**

## Find this library

- **PyPI:** [chumicro-http-server](https://pypi.org/project/chumicro-http-server/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_http_server)
- **Source:** [libraries/http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server)
