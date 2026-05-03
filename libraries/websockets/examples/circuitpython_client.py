"""WebSocket client demo for CircuitPython boards.

Connects to a host-side websocket echo server and prints every
message the server sends back.  Drives the client from a hand-rolled
tick loop so an LED can keep blinking through the handshake, frame
I/O, and the close handshake (Decision 0014).

Wire up your board's wifi via :mod:`chumicro_wifi` first; this
example assumes ``wifi.adapter`` is already connected.  Set
``WS_URL`` to a reachable echo server (the Postman test server,
your laptop, etc.) before deploying.

Hardware-only — the ``chumicro_sockets_factory`` helper imports
:mod:`chumicro_sockets` lazily and that imports ``wifi`` /
``socketpool`` on CircuitPython, which doesn't exist on CPython.
"""

import time

import wifi  # CircuitPython built-in
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory

WS_URL = "ws://192.168.1.42:8765/echo"


def now_ms():
    return time.monotonic_ns() // 1_000_000


client = WebSocketClient(
    connection_factory=chumicro_sockets_factory(radio=wifi.radio),
)
client.on_open = lambda: print("[client] open")
client.on_text = lambda text: print(f"[client] received: {text}")
client.on_close = lambda code, reason: print(
    f"[client] closed code={code} reason={reason!r}",
)

client.connect(WS_URL, timeout_ms=10000)

sent_count = 0
while client.state != WebSocketState.CLOSED:
    if client.check(now_ms()):
        client.handle(now_ms())
    if client.state == WebSocketState.OPEN and sent_count < 3:
        client.send_text(f"ping {sent_count}")
        sent_count += 1
        if sent_count == 3:
            client.close()
