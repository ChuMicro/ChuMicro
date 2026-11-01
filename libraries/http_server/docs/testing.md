# Testing Helpers

`chumicro_http_server.testing` stands in for the network side of a web server.  `FakeListener` replaces the listening socket that accepts browsers.  `request_bytes` builds the request a browser would send.  A test pushes that request through a real `HttpServer` and its real routes, then reads the response bytes, with no port, no network, and no waiting.  `pip install chumicro-http-server pytest` installs everything the tests on this page import, `chumicro-sockets` and `chumicro-timing` included.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_widget_route.py` and run `pytest test_widget_route.py`:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_http_server.testing import FakeListener, request_bytes
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_route_returns_the_path_parameter():
    browser = FakeSocket()
    browser.enqueue_recv(request_bytes(path="/widgets/7"))
    ticks = FakeTicks()
    server = HttpServer(
        transport_factory=lambda: FakeListener([(browser, ("192.168.1.20", 50000))]),
        ticks=ticks,
    )

    @server.route("/widgets/<id>")
    def widget(request):
        return build_response(200, json={"id": request.path_params["id"]})

    for _ in range(10):
        server.handle(ticks.ticks_ms())
        ticks.advance(1)

    assert browser.sent.startswith(b"HTTP/1.1 200 OK\r\n")
    assert browser.sent.endswith(b'{"id": "7"}')
```

`FakeSocket` from `chumicro_sockets.testing` plays the browser's connection.  It holds the request bytes.  `browser.sent` collects the bytes the server writes back.  `FakeTicks` moves the server's clock one millisecond per pass, so the loop finishes at once.

## `FakeListener`

`FakeListener(connections)` stands in for the listening socket an `HttpServer` opens.  Each entry in `connections` is a `(socket, peer)` pair, where `socket` is the client connection and `peer` is the `(host, port)` the server reports as `request.peer`.

| Call | What it does |
|---|---|
| `accept()` | Returns the next `(socket, peer)` pair.  With none left it raises `OSError(EAGAIN)`, as a listener does between clients. |
| `close()`, `setblocking(flag)` | Accept the call. |

An empty `FakeListener` plays a server nobody has connected to yet:

```python
from chumicro_http_server import HttpServer
from chumicro_http_server.testing import FakeListener
from chumicro_timing.testing import FakeTicks


def test_an_idle_tick_opens_no_connection():
    ticks = FakeTicks()
    server = HttpServer(transport_factory=lambda: FakeListener([]), ticks=ticks)

    server.handle(ticks.ticks_ms())

    assert server.in_flight == 0
```

## `request_bytes`

`request_bytes(method="GET", path="/", *, headers=None, body=b"")` returns one raw HTTP/1.1 request as `bytes`, ready for `FakeSocket.enqueue_recv`.  `headers` takes `(name, value)` pairs.  A non-empty `body` gets its `Content-Length` header added, so a POST test spells out only the body:

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_http_server.testing import FakeListener, request_bytes
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_sensor_route_reads_the_posted_json():
    browser = FakeSocket()
    browser.enqueue_recv(
        request_bytes(
            "POST",
            "/sensor",
            headers=[("Content-Type", "application/json")],
            body=b'{"celsius": 21.5}',
        ),
    )
    ticks = FakeTicks()
    server = HttpServer(
        transport_factory=lambda: FakeListener([(browser, ("192.168.1.20", 50000))]),
        ticks=ticks,
    )
    seen = {}

    @server.route("/sensor", methods=["POST"])
    def sensor(request):
        seen["payload"] = request.json()
        return build_response(201, json={"ok": True})

    for _ in range(10):
        server.handle(ticks.ticks_ms())
        ticks.advance(1)

    assert seen["payload"] == {"celsius": 21.5}
    assert browser.sent.startswith(b"HTTP/1.1 201 Created\r\n")
```

## API reference

::: chumicro_http_server.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
