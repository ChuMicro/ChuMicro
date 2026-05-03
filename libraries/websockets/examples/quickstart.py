"""WebSocket client + server in-memory loopback — runs everywhere.

Drives a :class:`WebSocketClient` and a :class:`WebSocketServer`
through a single tick loop, wired together via paired
:class:`FakeConnection` objects from
:mod:`chumicro_websockets.testing`.  No real sockets — proves the
runner contract works end-to-end with zero infrastructure.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    Server saw upgrade for path: /demo
    Server received: hello from client
    Client received: echo: hello from client
    Client and server both CLOSED.
"""

from chumicro_websockets import (
    CLOSE_NORMAL,
    WebSocketClient,
    WebSocketServer,
    WebSocketState,
)
from chumicro_websockets.testing import FakeConnection, FakeListener, TickClock


def on_connection(connection):
    print(f"Server saw upgrade for path: {connection.request_path}")
    connection.on_text = lambda text: (
        print(f"Server received: {text}"),
        connection.send_text(f"echo: {text}"),
    )


clock = TickClock()
client_socket = FakeConnection()
server_socket = FakeConnection()
listener = FakeListener()
listener.queue_accept(server_socket)

server = WebSocketServer(
    listener=listener,
    on_connection=on_connection,
    ticks_ms_func=clock.now,
    ticks_add_func=clock.add,
    ticks_diff_func=clock.diff,
)
client = WebSocketClient(
    connection_factory=lambda *_args, **_kwargs: client_socket,
    ticks_ms_func=clock.now,
    ticks_add_func=clock.add,
    ticks_diff_func=clock.diff,
)
client.on_text = lambda text: print(f"Client received: {text}")


def pump():
    if client_socket.outbound:
        server_socket.feed_inbound(bytes(client_socket.outbound))
        client_socket.outbound = bytearray()
    if server_socket.outbound:
        client_socket.feed_inbound(bytes(server_socket.outbound))
        server_socket.outbound = bytearray()


client.connect("ws://example.com/demo")
sent = False
for _tick in range(50):
    client.handle(clock.now())
    server.handle(clock.now())
    pump()
    if client.state == WebSocketState.OPEN and not sent:
        client.send_text("hello from client")
        sent = True
    if (
        sent
        and client.state == WebSocketState.OPEN
        and not server_socket.outbound
        and not client._tx_queue
        and client._tx_partial is None
    ):
        client.close(CLOSE_NORMAL, "demo done")
    if (
        client.state == WebSocketState.CLOSED
        and server.connection_count == 0
    ):
        break

print("Client and server both CLOSED.")
