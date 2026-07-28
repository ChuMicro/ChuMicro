# Testing Helpers

`chumicro_http_server.testing` provides `FakeListener` and `request_bytes`. Together they drive a real `HttpServer` through a full request and response without opening a socket, binding a port, or waiting on a real clock. The module declares the `__chumicro_test_support__` marker, and the deploy tool drops every module carrying it, so these fakes never ship to a board.

## `FakeListener`

`FakeListener(connections)` stands in for a listening socket. Each `accept()` pops one entry off *connections* and returns it; once the queue is empty, `accept()` raises `OSError(EAGAIN)`, which is what a real non-blocking listener does between clients. Every entry is the `(socket, peer)` pair the server expects, where *socket* is anything with the client-socket surface (`send`, `recv_into`, `close`, `setblocking`) and *peer* is the `(host, port)` tuple the request carries as `request.peer`. `chumicro_sockets.testing.FakeSocket` is the usual socket to hand it. `close()` and `setblocking()` are accepted and do nothing.

## `request_bytes`

`request_bytes(method="GET", path="/", *, headers=None, body=b"")` builds a raw HTTP/1.1 request as a single `bytes`, ready for `FakeSocket.enqueue_recv`. *headers* takes `(name, value)` tuples. A non-empty *body* gets its `Content-Length` header added for you, so a POST test only spells out what it actually cares about.

## Serving one request end to end

Queue the request bytes on a `FakeSocket`, hand that socket to a `FakeListener`, and tick the server until nothing is in flight. Assertions then read straight off `sock.sent`, the bytes the server wrote back.

```python
from chumicro_http_server import HttpServer, build_response
from chumicro_http_server.testing import FakeListener, request_bytes
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks

def drive(server, ticks, limit=50):
    """Tick until the server has no connection left in flight."""
    for _ in range(limit):
        server.handle(ticks.ticks_ms())
        if server.in_flight == 0:
            return
        ticks.advance(1)
    raise AssertionError("server still busy")

def test_route_returns_the_path_parameter():
    client = FakeSocket()
    client.enqueue_recv(request_bytes(path="/widgets/7"))
    ticks = FakeTicks()

    server = HttpServer(
        transport_factory=lambda: FakeListener([(client, ("127.0.0.1", 50000))]),
        ticks=ticks,
    )

    @server.route("/widgets/<id>")
    def widget(request):
        return build_response(200, json={"id": request.path_params["id"]})

    drive(server, ticks)

    assert client.sent.startswith(b"HTTP/1.1 200 OK\r\n")
    assert client.sent.endswith(b'{"id": "7"}')
```

`FakeTicks` keeps the loop instant: nothing sleeps, and `ticks.advance(1)` moves the server's deadlines forward as fast as the test runs.

## Asserting on a request body

`request_bytes` fills in `Content-Length`, so a handler that parses JSON gets a well-formed request without the test counting bytes:

```python
def test_sensor_route_reads_the_posted_json():
    client = FakeSocket()
    client.enqueue_recv(
        request_bytes(
            "POST",
            "/sensor",
            headers=[("Content-Type", "application/json")],
            body=b'{"celsius": 21.5}',
        ),
    )
    ticks = FakeTicks()
    seen = {}

    server = HttpServer(
        transport_factory=lambda: FakeListener([(client, ("127.0.0.1", 50000))]),
        ticks=ticks,
    )

    @server.route("/sensor", methods=["POST"])
    def sensor(request):
        seen["payload"] = request.json()
        return build_response(201, json={"ok": True})

    drive(server, ticks)

    assert seen["payload"] == {"celsius": 21.5}
    assert client.sent.startswith(b"HTTP/1.1 201 Created\r\n")
```

## Testing the quiet path

A `FakeListener` with an empty queue raises `EAGAIN` on every `accept()`, which is the shape of a server nobody has connected to yet. Use it to assert that an idle tick does nothing expensive:

```python
def test_idle_tick_opens_no_connection():
    ticks = FakeTicks()
    server = HttpServer(transport_factory=lambda: FakeListener([]), ticks=ticks)

    server.handle(ticks.ticks_ms())

    assert server.in_flight == 0
```

## Using these fakes in your own tests

Installing `chumicro-http-server` puts `chumicro_http_server.testing` on your path, so your own suite imports the fakes the library's own tests use:

```python
from chumicro_http_server.testing import FakeListener, request_bytes
```

That is all the setup there is. Your route handlers run against real parsing and real response writing, and the test needs no network, no free port, and no waiting.

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_http_server.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
