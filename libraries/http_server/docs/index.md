---
title: "chumicro-http-server: HTTP server on CircuitPython and MicroPython boards"
---

# chumicro-http-server

**A web server for CircuitPython and MicroPython boards that answers requests while your LED keeps blinking.**

Write a function for each URL, mark it with `@server.route("/path")`, and call `server.handle()` from your `while True:` loop.  Each call accepts a waiting visitor, moves every open request a small step along, and returns within a few milliseconds, so the rest of your program keeps running while the board serves pages.  The server answers several clients at once, routes by method and path, reads JSON bodies, streams responses bigger than the board's memory, and serves HTTPS on the boards listed under [TLS server (HTTPS)](guide.md#tls-server-https).  The same code runs on CPython, so your routes run in tests on a laptop.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_http_server

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_http_server

# CPython
pip install chumicro-http-server
```

The quick example joins wifi with `chumicro-wifi`.  Its `Runner` loop comes from `chumicro-runner`.  Install both the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Serve a page and a JSON echo route on port 8080:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))

# The server opens port 8080 on its first handle() call.
# CircuitPython needs radio=, and MicroPython ignores it.
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

Once `wifi.connected` is true, `wifi.ip` holds the board's address: open `http://<that address>:8080/` in a browser.

`wifi` and `server` are services, objects a loop drives through two methods.  `check(now_ms)` returns `True` when the service has work to do.  `handle(now_ms)` does one small step of that work.  `now_ms` is the millisecond reading from `ticks_ms()`, taken once per pass and passed to both.  A visitor can arrive at any moment, so the server's `check()` always returns `True`.

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/):

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(wifi)
runner.add(server)

while True:
    now_ms = runner.tick()   # wifi and the server each take one small step
    runner.wait(now_ms)      # sleep until a visitor connects or wifi needs attention
```

`runner.wait(now_ms)` watches the listening socket, so the board sleeps between requests.

## Documentation

- [User Guide](guide.md): how the loop serves requests, settings from a deploy, the runner pattern, routing and path parameters, limits, streaming large bodies, the TLS server, and platform notes
- [API Reference](api.md): `HttpServer`, `Request` / `Response`, `build_response`, and the streaming submodule
- [Testing Helpers](testing.md): serving requests in a unit test with `FakeListener`, with no network

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
