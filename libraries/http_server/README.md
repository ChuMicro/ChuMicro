# chumicro-http-server

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A web server for CircuitPython and MicroPython boards that answers requests while your LED keeps blinking.**

Write a function for each URL, mark it with `@server.route("/path")`, and call `server.handle()` from your `while True:` loop.  Each call accepts a waiting visitor, moves every open request a small step along, and returns within a few milliseconds, so the rest of your program keeps running while the board serves pages.  The server answers several clients at once, routes by method and path, reads JSON bodies, streams responses bigger than the board's memory, and serves HTTPS on the boards listed under [TLS server (HTTPS)](#tls-server-https).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_http_server

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_http_server

# CPython
pip install chumicro-http-server
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Quick example

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))

# The server opens port 8080 on its first handle() call.  radio= matters
# on CircuitPython only; MicroPython ignores it.
server = HttpServer(
    transport_factory=lambda: listener("0.0.0.0", 8080, radio=wifi.adapter.radio),
)

@server.route("/")
def home(request):
    return build_response(200, html="<h1>Hello from your board</h1>")

@server.route("/echo", methods=["POST"])
def echo(request):
    return build_response(200, json={"echoed": request.json()})

while True:
    now_ms = ticks_ms()
    if wifi.check(now_ms):                       # join wifi, and rejoin after a drop
        wifi.handle(now_ms)
    if wifi.connected and server.check(now_ms):  # serve once the board has an address
        server.handle(now_ms)
```

Once `wifi.connected` is true, `wifi.ip` holds the board's address: open `http://<that address>:8080/` in a browser.  The example joins wifi with [`chumicro-wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), installed the same way as this library.

Every ChuMicro service has the same two methods.  `check(now_ms)` says whether it has work, and `handle(now_ms)` does a small piece of it and returns.  `now_ms` is a millisecond count from `ticks_ms()`, read once per pass and shared.  A server always has work, because a visitor can arrive at any moment, so its `check()` always returns `True`.

In a program with more going on, hand the loop to [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner).  A `Runner` holds your services and timed functions, and each `tick()` gives every one of them a turn:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(wifi)
runner.add(server)

while True:
    now_ms = runner.tick()   # wifi and the server each take one small step
    runner.wait(now_ms)      # then the board sleeps until there is more to do
```

`wait()` sleeps on the listening socket, so the board idles between requests instead of spinning.

## What's included

| Symbol | Purpose |
|---|---|
| `HttpServer` | The server.  Register routes with `@server.route(...)`, then call `check(now_ms)` and `handle(now_ms)` from your loop.  `HttpServer.from_config(config, radio=...)` builds one from settings a deploy put on the board. |
| `Request` | What a route receives: `method`, `path`, `query`, `path_params`, `headers`, `body`, `peer`, plus `json()` and `text()`. |
| `Response` | What a route returns: `status_code`, `reason`, `headers`, `body`. |
| `build_response(status, *, body, json, text, html, headers)` | Builds a `Response` and sets `Content-Type` to match `json=`, `text=`, or `html=`. |
| `streaming.build_streaming_response(status, *, source, content_length, headers)` | In the opt-in `chumicro_http_server.streaming` submodule.  Sends a body bigger than the board's memory, filled one small buffer at a time by your `source(buffer)` function. |
| `RequestParser` | The incremental request parser the server runs on, for tests and custom servers. |
| `parse_query` / `split_target` | URL helpers: split `/path?a=1` into path and query, and parse the query into a dict. |
| `ServerError` and subclasses | Errors for malformed or oversized requests.  Inside `HttpServer` you never catch them: an oversized request gets a `413`, `414`, or `431` response, and a malformed one is dropped. |

The server closes each connection after one response (`Connection: close`).  It reads request bodies sent with `Content-Length`, and drops a chunked upload without answering.

To send a body bigger than the board's memory (a log dump, a file, a long export), return a **streaming response** from the opt-in `chumicro_http_server.streaming` submodule.  The server pulls the body from your function one small buffer at a time and picks Content-Length or chunked framing for you:

```python
from chumicro_http_server.streaming import build_streaming_response, SOURCE_EOF

@server.route("/log")
def log_dump(request):
    def source(buffer):
        count = read_next_block_into(buffer)   # your storage read; 0 <= count <= len(buffer)
        return count if count else SOURCE_EOF  # SOURCE_EOF (-1) ends the body
    return build_streaming_response(200, source=source)
```

See the [user guide](https://chumicro.com/ChuMicro/http_server/stable/guide/#streaming-large-response-bodies) for the source contract, framing rules, fairness between connections, and buffer sizing.

## Where this fits

Built on [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) for the listening socket, [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the millisecond clock, and [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) for `from_config`; installing this library installs all three.  [`chumicro-wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) joins the network, [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) runs the server beside your other tasks, and [`chumicro-websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) adds WebSocket connections on the same board.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Pure Python, no native extensions.

### TLS server (HTTPS)

For HTTPS, hand the server a TLS listener: build an SSL context from your certificate and key with [`chumicro_sockets.ssl_context_with_cert_and_key_paths`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), then pass `tls=True, context=...` to `listener` inside your `transport_factory`.  The rest of the server stays the same.  Tested on real boards:

| Runtime + board | TLS server | Notes |
|---|---|---|
| CircuitPython on ESP32-S2 (Lolin S2) | ✅ Works | RSA-2048 certificate.  Each handshake needs tens of KB of free memory, so leave headroom. |
| CircuitPython on rp2 (Pi Pico W / Pi Pico 2 W) | ❌ Refused (`UnsupportedSSLConfigError`) | `listener(tls=True)` raises up front.  The CYW43 wifi chip's TLS server path fails mid-handshake with `OSError(32)` and leaves wifi wedged until a USB power cycle.  Use an ESP32-family board, or MicroPython on rp2. |
| MicroPython on ESP32-S2 | ✅ Works | Hardware-accelerated handshake; about 1 KB of heap. |
| MicroPython on rp2 (Pi Pico W) | ✅ Works (RSA-2048 only) | DER-encoded key; about 25 KB of heap per handshake; ECC keys fail when the context is built. |

The board runs each TLS handshake in one go when it accepts the connection, so your loop pauses until the handshake finishes.  After that, the connection goes back to small steps per `handle()` call.

## Examples

| Example | What it shows |
|---|---|
| `simple_server.py` | Serves an HTML page, a JSON status route, and a POST echo route, and prints a status line every 30 seconds while it waits for visitors.  Open it in a browser or drive it with `curl`.  Runs on CircuitPython and MicroPython. |

## Wiring wifi credentials

`simple_server.py` joins your wifi before it serves.  Set `WIFI_SSID` and `WIFI_PASSWORD` at the top of the file, or deploy it from a ChuMicro workspace with `chumicro-workspace deploy-example http_server simple_server`, which takes them from `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through both.  The library reads no credentials itself: your code joins wifi, then gives the server a function that opens its listening socket.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/http_server/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/http_server/experimental/)**

## Find this library

- **PyPI:** [chumicro-http-server](https://pypi.org/project/chumicro-http-server/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_http_server) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_http_server)
- **Source:** [libraries/http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
