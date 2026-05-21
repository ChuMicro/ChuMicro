"""WebSocket echo server demo for CircuitPython / MicroPython boards.

Brings wifi up via the local ``helpers`` module, accepts inbound
websocket connections on the configured host/port, and echoes every
text message back with an ``echo:`` prefix.  Drives the server from
a hand-rolled tick loop so an LED can keep blinking through accepts,
handshake, frame I/O, and close.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* WebSocket server (read by ``WebSocketServer.from_config``):
  ``websockets.server.host`` / ``websockets.server.port`` /
  ``websockets.server.max_message_bytes`` — all optional, defaults
  to ``0.0.0.0:8765`` with the library's message-size cap.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to placeholder constants below
(server bind defaults to ``0.0.0.0:8765`` from the library).

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example websockets server --device <id>
"""

#: Tooling reads this marker to allow the example on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_websockets import WebSocketServer
from helpers import runtime_config, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")


def on_connection(connection):
    print(f"[server] accept {connection.request_path}")
    connection.on_text = lambda text: (
        print(f"[server] recv: {text}"),
        connection.send_text(f"echo: {text}"),
    )
    connection.on_close = lambda code, reason: print(
        f"[server] closed code={code} reason={reason!r}",
    )


server = WebSocketServer.from_config(config, on_connection, radio=radio)

bound_host = config.get("websockets.server.host", "0.0.0.0")
bound_port = config.get("websockets.server.port", 8765)
print(f"[server] listening on {bound_host}:{bound_port}")

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
    time.sleep(0.02)
