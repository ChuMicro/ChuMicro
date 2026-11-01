"""Send a message to a WebSocket server every five seconds, and reconnect when the connection drops.

The board joins wifi and connects to a WebSocket echo server.  Every
five seconds it sends ``hello 1``, ``hello 2``, and so on, and prints
each reply the server sends back.  Stop the server and the board
prints why the connection closed, then tries again every five seconds
until the server is back.

What you need
=============

An echo server on the same network as the board.  The quickest one
runs on your laptop: install the ``websockets`` package with
``pip install websockets``, then run this line.  It sends every
message straight back with ``echo:`` in front::

    python -c "from websockets.sync.server import serve; serve(lambda ws: [ws.send('echo: ' + m) for m in ws], '0.0.0.0', 8765).serve_forever()"

Your laptop's IP address goes in ``SERVER_URL``.  Find it with
``ipconfig getifaddr en0`` on macOS, ``hostname -I`` on Linux, or
``ipconfig`` on Windows.

A second board running ``server.py`` from this folder works too.  It
prints the URL to use when it starts, and it also sends a ``count``
message every five seconds, which this board prints as well.

Setup
=====

1. Set ``SERVER_URL`` below, for example ``ws://192.168.1.42:8765/``.
2. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.
3. Deploy and watch the output::

       chumicro-workspace deploy-example websockets client

A deploy from a ``chumicro-workspace`` also copies your ``secrets.toml``
to the board, and its values win over the constants: ``ssid`` and
``password`` under ``[wifi]``, and ``connect_url`` under
``[websockets.client]``.

Example output, with the laptop server stopped after the second reply
and then started again.  The text after ``connector failed:`` is the
board's own network error, so it varies from board to board::

    WIFI_OK ip=192.168.1.57
    [client] connecting to ws://192.168.1.42:8765/
    [client] connected
    [client] sent: hello 1
    [client] received: echo: hello 1
    [client] sent: hello 2
    [client] received: echo: hello 2
    [client] closed code=1011 reason='peer closed TCP without sending a CLOSE frame'
    [client] connecting to ws://192.168.1.42:8765/
    [client] closed code=1011 reason='connector failed: ...'
    [client] connecting to ws://192.168.1.42:8765/
    [client] connected
    [client] sent: hello 3
    [client] received: echo: hello 3
"""  # noqa: E501 - the laptop command has to stay on one line to copy and paste

#: Tooling reads this marker to allow the example on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_runner import Runner
from chumicro_websockets import WebSocketClient, WebSocketState
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
SERVER_URL = "ws://192.168.1.42:8765/"  # replace with your server's address
SEND_EVERY_MS = 5000

config = runtime_config()
server_url = config.get("websockets.client.connect_url", SERVER_URL)

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# A Runner gives every task registered with it a turn on each pass of
# the loop at the bottom of this file.
runner = Runner()


def start_client():
    """Open a new connection to the server and register it with the runner."""
    client = WebSocketClient.from_config(config, radio=radio)
    client.on_open = lambda: print("[client] connected")
    client.on_text = lambda text: print(f"[client] received: {text}")
    client.on_close = lambda code, reason: print(f"[client] closed code={code} reason={reason!r}")
    print(f"[client] connecting to {server_url}")
    client.connect(server_url)
    return client, runner.add(client)


client, client_task = start_client()
sent_count = 0


def send_or_reconnect(now_ms):
    """Send the next message while connected; start a new connection once the old one has closed."""
    global client, client_task, sent_count
    if client.state == WebSocketState.OPEN:
        sent_count += 1
        message = f"hello {sent_count}"
        client.send_text(message)
        print(f"[client] sent: {message}")
    elif client.state == WebSocketState.CLOSED:
        # A client connects only once, so a closed one is swapped for a new one.
        client_task.remove()
        client, client_task = start_client()


runner.add_periodic(send_or_reconnect, period_ms=SEND_EVERY_MS)

while True:
    now_ms = runner.tick()  # the client moves its messages; the timer fires when due
    runner.wait(now_ms)  # then the CPU idles until a message arrives or the timer is due
