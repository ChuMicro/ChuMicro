"""WebSocket echo server demo for CircuitPython boards.

Accepts inbound websocket connections on the board's IP at port
8765 and echoes every text message back with an ``echo:`` prefix.
Drives the server from a hand-rolled tick loop so an LED can keep
blinking through accepts, handshake, frame I/O, and close (Decision 0014).

Wire up your board's wifi via :mod:`chumicro_wifi` first; this
example assumes ``wifi.adapter`` is already connected.

Hardware-only — :mod:`chumicro_sockets` imports ``wifi`` /
``socketpool`` on CircuitPython, which doesn't exist on CPython.
"""

import time

import wifi  # CircuitPython built-in
from chumicro_sockets import tcp_listening_socket
from chumicro_websockets import WebSocketServer

PORT = 8765


def now_ms():
    return time.monotonic_ns() // 1_000_000


def on_connection(connection):
    print(f"[server] accept {connection.request_path}")
    connection.on_text = lambda text: (
        print(f"[server] recv: {text}"),
        connection.send_text(f"echo: {text}"),
    )
    connection.on_close = lambda code, reason: print(
        f"[server] closed code={code} reason={reason!r}",
    )


listener = tcp_listening_socket("0.0.0.0", PORT, radio=wifi.radio)
server = WebSocketServer(
    listener=listener,
    on_connection=on_connection,
    max_connections=2,
)

print(f"[server] listening on {wifi.radio.ipv4_address}:{PORT}")
while True:
    if server.check(now_ms()):
        server.handle(now_ms())
