# chumicro-http-server

**Non-blocking HTTP/1.1 server for CircuitPython, MicroPython, and CPython.**

Each connection is a state machine the server advances one chunk per runner tick — an LED keeps blinking while requests are being served.  Built on `chumicro-sockets` and `chumicro-timing` only.

## Quick example

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_timing import ticks_ms

server = HttpServer(
    transport_factory=lambda: listener(
        host="0.0.0.0", port=8080, radio=wifi.radio,
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
    if server.check(now):
        server.handle(now)
```

## Documentation

- [User Guide](guide.md) — routing, response helpers, TLS server, platform notes
- [API Reference](api.md) — full API documentation

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
