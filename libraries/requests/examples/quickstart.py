"""chumicro-requests quickstart — plain HTTP GET against an in-memory socket.

Demonstrates the runner-shaped client + RequestHandle pattern without
touching a real network: a hand-rolled connection factory hands the
client a pre-scripted ``FakeSocket`` whose recv queue holds a canned
HTTP/1.1 response.

Runs on CPython.  The same code shape applies on MicroPython and
CircuitPython once the connection_factory is swapped to
``chumicro_sockets_factory(radio=wifi.radio)``.

Example output::

    Status: 200 OK
    Server header: chumicro-quickstart
    Body: b'hello from quickstart'
"""

from chumicro_requests import HttpClient
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def make_factory(scripted_response: bytes):
    """Return a connection_factory that always hands out the same FakeSocket."""
    def factory(host, port, use_tls):  # noqa: ARG001 — fake ignores args
        socket = FakeSocket()
        socket.enqueue_recv(scripted_response)
        return socket

    return factory


canned_response = (
    b"HTTP/1.1 200 OK\r\n"
    b"Server: chumicro-quickstart\r\n"
    b"Content-Length: 21\r\n"
    b"Content-Type: text/plain\r\n"
    b"\r\n"
    b"hello from quickstart"
)

ticks = FakeTicks()
client = HttpClient(
    connection_factory=make_factory(canned_response),
    ticks_ms_func=ticks.ticks_ms,
    ticks_add_func=ticks.ticks_add,
    ticks_diff_func=ticks.ticks_diff,
)

handle = client.get("http://example.test/", timeout_ms=1000)
while not handle.done:
    if client.check(ticks.ticks_ms()):
        client.handle(ticks.ticks_ms())
    ticks.advance(1)

response = handle.result
print(f"Status: {response.status_code} {response.reason}")
print(f"Server header: {response.headers['server']}")
print(f"Body: {response.body!r}")
