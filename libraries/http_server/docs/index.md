---
title: "chumicro-http-server: HTTP server on CircuitPython and MicroPython boards"
---

# chumicro-http-server

**Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.**

Each connection is a state machine the server advances one chunk per runner tick, so an LED keeps blinking while requests are being served.  Built on `chumicro-sockets` and `chumicro-timing` only.

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

wifi = WifiService(WifiConfig(ssid="home-wifi", password="secret"))

server = HttpServer(
    # radio= is the CircuitPython radio handle; MicroPython and CPython ignore it.
    transport_factory=lambda: listener(
        host="0.0.0.0", port=8080, radio=wifi.adapter.radio,
    ),
)

@server.route("/")
def index(request):
    return build_response(200, html="<h1>Hello from a Pi Pico W</h1>")

@server.route("/widgets/<id>")
def widget(request):
    return build_response(200, json={"id": request.path_params["id"]})

while True:
    now = ticks_ms()
    if wifi.check(now):        # keeps the link up and reconnects after a drop
        wifi.handle(now)
    if server.check(now):
        server.handle(now)
```

In a program with more going on, hand the loop to `chumicro-runner`:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add(wifi)
runner.add(server)

while True:
    now = runner.tick()
    runner.wait(now)
```

`wait()` sleeps on the listening socket until a request arrives, which turns the loop from a busy spin into an idle one.

## Documentation

- [User Guide](guide.md): routing and path parameters, the runner pattern, tick-fairness knobs, streaming large bodies, TLS server, platform notes
- [API Reference](api.md): `HttpServer`, `Request` / `Response`, `build_response`, and the streaming submodule
- [Testing Helpers](testing.md): using `FakeListener` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
