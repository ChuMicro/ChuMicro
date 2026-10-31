---
title: "chumicro-http-server: HTTP server on CircuitPython and MicroPython boards"
---

# chumicro-http-server

**A web server for CircuitPython and MicroPython boards that answers requests while your LED keeps blinking.**

Write a function for each URL, mark it with `@server.route("/path")`, and call `server.handle()` from your `while True:` loop.  Each call accepts a waiting visitor, moves every open request a small step along, and returns within a few milliseconds, so the rest of your program keeps running while the board serves pages.  It also runs on CPython, which is how you test your routes on a laptop.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_http_server

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_http_server

# CPython
pip install chumicro-http-server
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

Once `wifi.connected` is true, `wifi.ip` holds the board's address: open `http://<that address>:8080/` in a browser.  The example joins wifi with [`chumicro-wifi`](https://chumicro.com/ChuMicro/wifi/stable/), installed the same way as this library.

In a program with more going on, hand the loop to [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/).  A `Runner` holds your services and timed functions, and each `tick()` gives every one of them a turn:

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

## Documentation

- [User Guide](guide.md): how the loop serves requests, routing and path parameters, settings from a deploy, limits, streaming large bodies, the TLS server, and platform notes
- [API Reference](api.md): `HttpServer`, `Request` / `Response`, `build_response`, and the streaming submodule
- [Testing Helpers](testing.md): serving requests in a unit test with `FakeListener`, no network needed

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
