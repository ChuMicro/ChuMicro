"""chumicro-http-server quickstart — request/response cycle in-memory.

Demonstrates the runner-shaped server + Request/Response value objects
without touching a real network: a fake listener hands the server a
pre-scripted ``FakeSocket`` whose recv queue holds a canned HTTP/1.1
request.  The handler builds a response, the server writes it back to
the FakeSocket's ``sent`` buffer, and we print the result.

Runs on CPython.  The same code shape applies on MicroPython and
CircuitPython once the ``listener_factory`` is swapped to
``tcp_listening_socket(host, port, radio=wifi.radio)``.

Example output::

    Request method: GET
    Request path: /api
    Response sent (head):
    HTTP/1.1 200 OK
    Content-Length: 26
    Connection: close
    Content-Type: application/json
"""

from chumicro_http_server import HttpServer, build_response
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class FakeListener:
    def __init__(self, queued):
        self._queued = list(queued)

    def accept(self):
        if not self._queued:
            raise OSError(11, "would block")
        return self._queued.pop(0)

    def close(self):
        pass

    def setblocking(self, _flag):
        pass


def handler(request):
    print(f"Request method: {request.method}")
    print(f"Request path: {request.path}")
    return build_response(200, json={"ok": True, "path": request.path})


canned_request = (
    b"GET /api HTTP/1.1\r\n"
    b"Host: example.test\r\n"
    b"\r\n"
)
client_socket = FakeSocket()
client_socket.enqueue_recv(canned_request)

ticks = FakeTicks()
server = HttpServer(
    listener_factory=lambda: FakeListener([(client_socket, ("127.0.0.1", 1))]),
    handler=handler,
    ticks_ms_func=ticks.ticks_ms,
    ticks_add_func=ticks.ticks_add,
    ticks_diff_func=ticks.ticks_diff,
)

# Drive the server until the in-flight connection finishes.
for _ in range(20):
    server.handle(ticks.ticks_ms())
    if server.in_flight == 0:
        break
    ticks.advance(1)

response_text = bytes(client_socket.sent).decode("utf-8")
print("Response sent (head):")
for line in response_text.split("\r\n")[:6]:
    print(line)
