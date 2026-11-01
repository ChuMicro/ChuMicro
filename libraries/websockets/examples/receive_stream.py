"""Print every message a WebSocket server streams to your board, and reconnect when the stream ends.

The board joins wifi, connects to a WebSocket server, and prints each
message the server sends.  When the server closes the connection, or
the connection fails, the board prints why and connects again within
five seconds.

``client.py`` handles incoming messages with callbacks.  This example
reads them with a generator instead: a function that pauses at each
``yield`` and carries on from that line on a later pass of the loop.
``message = yield from client.next_message()`` pauses until the next
message arrives, so the receive code reads top to bottom.

What you need
=============

A WebSocket server that sends messages on its own.  The quickest one
runs on your laptop: install the ``websockets`` package with
``pip install websockets``, then run this line.  It sends the time once
a second, ten times, then closes the connection, so you also see the
board reconnect::

    python -c "import time; from websockets.sync.server import serve; serve(lambda ws: [(ws.send(time.strftime('%H:%M:%S')), time.sleep(1)) for _ in range(10)], '0.0.0.0', 8765).serve_forever()"

Your laptop's IP address goes in ``SERVER_URL``.  Find it with
``ipconfig getifaddr en0`` on macOS, ``hostname -I`` on Linux, or
``ipconfig`` on Windows.

A second board running ``server.py`` from this folder works too.  It
prints the URL to use when it starts and sends a ``count`` message
every five seconds.

Setup
=====

1. Set ``SERVER_URL`` below, for example ``ws://192.168.1.42:8765/``.
2. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.
3. Deploy and watch the output::

       chumicro-workspace deploy-example websockets receive_stream

A deploy from a ``chumicro-workspace`` also copies your ``secrets.toml``
to the board, and its values win over the constants: ``ssid`` and
``password`` under ``[wifi]``, and ``connect_url`` under
``[websockets.client]``.

Example output against the laptop server::

    WIFI_OK ip=192.168.1.57
    [client] connecting to ws://192.168.1.42:8765/
    [client] received: 14:02:11
    [client] received: 14:02:12
    ...
    [client] received: 14:02:20
    [client] closed after 10 message(s): code=1000 reason=''
    [client] connecting to ws://192.168.1.42:8765/
    [client] received: 14:02:25
"""  # noqa: E501 - the laptop command has to stay on one line to copy and paste

#: Tooling reads this marker to allow the example on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_runner import Runner
from chumicro_websockets import WebSocketClient, WebSocketState
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
SERVER_URL = "ws://192.168.1.42:8765/"  # replace with your server's address
RETRY_EVERY_MS = 5000

config = runtime_config()
server_url = config.get("websockets.client.connect_url", SERVER_URL)

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# A Runner gives every task registered with it a turn on each pass of
# the loop at the bottom of this file.
runner = Runner()


def print_messages(client):
    """Print each message from one connection, until that connection closes."""
    received = 0
    while True:
        # Pause here until a message arrives.  None means the connection closed.
        message = yield from client.next_message()
        if message is None:
            break
        received += 1
        if message.is_text:
            print(f"[client] received: {message.text}")
        else:
            print(f"[client] received {len(message.data)} bytes")
    print(
        f"[client] closed after {received} message(s): "
        f"code={client.last_close_code} reason={client.last_close_reason!r}",
    )


def start_client():
    """Open a new connection and register it, then its printer, with the runner."""
    client = WebSocketClient.from_config(config, radio=radio)
    print(f"[client] connecting to {server_url}")
    client.connect(server_url)
    # The client reads the network; the generator prints what it read.
    client_task = runner.add(client)
    runner.add_generator(print_messages(client))
    return client, client_task


client, client_task = start_client()


def reconnect_if_closed(now_ms):
    """Start a new connection once the old one has closed."""
    global client, client_task
    if client.state == WebSocketState.CLOSED:
        # A client connects only once, so a closed one is swapped for a new one.
        client_task.remove()
        client, client_task = start_client()


runner.add_periodic(reconnect_if_closed, period_ms=RETRY_EVERY_MS)

while True:
    now_ms = runner.tick()  # the client reads the network; the generator prints what arrived
    runner.wait(now_ms)  # then the CPU idles until a message arrives or a retry is due
