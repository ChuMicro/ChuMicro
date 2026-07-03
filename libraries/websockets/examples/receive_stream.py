"""WebSocket receive-stream client via next_message on a real board.

Brings wifi up via the local ``helpers`` module, connects to a
configured server, then receives every message with a
``yield from ws.next_message()`` loop driven by ``Runner.add_generator``
— wait for a message, print it, wait for the next, until the server
closes the stream.

Pair with ``client.py``, which uses the ``on_text`` / ``on_binary``
callbacks and a hand-rolled tick loop; this one shows the linear
receive loop where the session and the consumer are both registered
with the runner.

Prerequisite
============

Needs a reachable websocket server that sends messages.  Run
``chumicro_websockets`` server on a desktop or a second board and set
``websockets.client.connect_url`` (see ``client.py`` for the same
setup).  If no URL is configured, the example prints a SETUP message
and exits cleanly.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* App-level: ``websockets.client.connect_url`` — the server to connect
  to, passed to ``ws.connect(url)``.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example websockets receive_stream --device <id>
"""

#: Tooling reads this marker to allow the example on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_runner import Runner
from chumicro_websockets import WebSocketClient
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

config = runtime_config()
connect_url = config.get("websockets.client.connect_url")
if not connect_url:
    print("SETUP: this example needs a reachable websocket server.")
    print("       Set `websockets.client.connect_url` in secrets.toml —")
    print("       e.g. ws://192.168.1.42:8765/ — and redeploy.")
    raise SystemExit(0)

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

ws = WebSocketClient.from_config(config, radio=radio)
ws.on_open = lambda: print("[client] open")
ws.connect(connect_url, timeout_ms=10_000)


def receive_stream():
    received = 0
    while True:
        message = yield from ws.next_message()
        if message is None:
            break
        received += 1
        text = message.text if message.is_text else repr(message.data)
        print(f"[client] message {received}: {text}")
    print(f"[client] stream closed after {received} message(s)")


runner = Runner()
runner.add(ws)
handle = runner.add_generator(receive_stream())
runner.run_until(handle)
