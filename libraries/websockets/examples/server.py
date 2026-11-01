"""Run a WebSocket server on your board that echoes messages and sends a count every five seconds.

The board joins wifi, prints the address to connect to, and waits for
WebSocket clients.  Every text message a client sends comes straight
back with ``echo:`` in front.  Every five seconds the board also sends
``count 1``, ``count 2``, and so on to each connected client, so you
can watch the board push data without being asked.  The server keeps
running until you unplug the board.

Setup
=====

1. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.
2. Deploy and watch the output::

       chumicro-workspace deploy-example websockets server

3. Connect from a laptop on the same network with the ``websockets``
   package's interactive client, using the address the board printed::

       pip install websockets
       python -m websockets ws://192.168.1.57:8765/

   Type a line and press Enter, and the board sends it back.  The
   ``count`` messages show up on their own.  Press Ctrl-D to disconnect.

``client.py`` and ``receive_stream.py`` from this folder, running on a
second board, also work as clients.

A deploy from a ``chumicro-workspace`` also copies your ``secrets.toml``
to the board, and its values win over the constants: ``ssid`` and
``password`` under ``[wifi]``, and ``port`` under ``[websockets.server]``
to listen somewhere other than 8765.

Example output, with one laptop connecting, sending ``hi board``, and
disconnecting::

    WIFI_OK ip=192.168.1.57
    [server] listening on ws://192.168.1.57:8765/
    [server] sent count 1 to 0 client(s)
    [server] client connected on path /
    [server] received: hi board
    [server] sent count 2 to 1 client(s)
    [server] client left code=1000 reason=''
    [server] sent count 3 to 0 client(s)
"""

#: Tooling reads this marker to allow the example on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_runner import Runner
from chumicro_websockets import WebSocketServer, WebSocketState
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
COUNT_EVERY_MS = 5000

config = runtime_config()
port = config.get("websockets.server.port", 8765)

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")


def on_connection(connection):
    """Set up one new client: echo its text messages and say when it leaves."""
    print(f"[server] client connected on path {connection.request_path}")

    def echo(text):
        print(f"[server] received: {text}")
        connection.send_text(f"echo: {text}")

    connection.on_text = echo
    connection.on_close = lambda code, reason: print(f"[server] client left code={code} reason={reason!r}")


server = WebSocketServer.from_config(config, on_connection, radio=radio)
count = 0


def send_count(now_ms):
    """Send the next count to every connected client."""
    global count
    count += 1
    sent_to = 0
    for connection in server.connections:
        # A client still finishing its handshake cannot take messages yet.
        if connection.state == WebSocketState.OPEN:
            connection.send_text(f"count {count}")
            sent_to += 1
    print(f"[server] sent count {count} to {sent_to} client(s)")


# A Runner gives every task registered with it a turn on each pass of
# the loop at the bottom of this file.
runner = Runner()
runner.add(server)
runner.add_periodic(send_count, period_ms=COUNT_EVERY_MS)

print(f"[server] listening on ws://{ip}:{port}/")

while True:
    now_ms = runner.tick()  # the server accepts clients and moves their messages
    runner.wait(now_ms)  # then the CPU idles until a client needs attention or a count is due
