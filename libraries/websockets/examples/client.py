"""WebSocket client demo for CircuitPython / MicroPython boards.

Brings wifi up via the local ``helpers`` module, connects to a
configured echo server, and prints every message the server sends
back.  Drives the client from a hand-rolled tick loop so an LED can
keep blinking through the handshake, frame I/O, and the close
handshake.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* WebSocket client (read by ``WebSocketClient.from_config``):
  ``websockets.client.max_message_bytes`` (optional, library default).
* App-level: ``websockets.client.connect_url`` is read by this
  example and passed to ``client.connect(url)`` — it's declared in
  the manifest because users need to set it per-project, but
  ``WebSocketClient.from_config`` doesn't consume it (URL is a
  per-connection argument).

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds and the connect URL fall back to placeholder
constants below — edit them first.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example websockets client --device <id>
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the websocket client
#: is pure-Python.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_websockets import WebSocketClient, WebSocketState
from helpers import runtime_config, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
WS_URL = "ws://192.168.1.42:8765/echo"

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

connect_url = config.get("websockets.client.connect_url", WS_URL)

client = WebSocketClient.from_config(config, radio=radio)
client.on_open = lambda: print("[client] open")
client.on_text = lambda text: print(f"[client] received: {text}")
client.on_close = lambda code, reason: print(
    f"[client] closed code={code} reason={reason!r}",
)

client.connect(connect_url, timeout_ms=10_000)

sent_count = 0
while client.state != WebSocketState.CLOSED:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
    if client.state == WebSocketState.OPEN and sent_count < 3:
        client.send_text(f"ping {sent_count}")
        sent_count += 1
        if sent_count == 3:
            client.close()
