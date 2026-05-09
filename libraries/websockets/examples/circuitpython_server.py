"""WebSocket echo server demo for CircuitPython / MicroPython boards.

Accepts inbound websocket connections on the configured host/port
and echoes every text message back with an ``echo:`` prefix.  Drives
the server from a hand-rolled tick loop so an LED can keep blinking
through accepts, handshake, frame I/O, and close.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi: ``WifiConfig.try_from_config(config)`` reads ``wifi.ssid`` /
  ``wifi.password`` plus optional tunables.
* WebSocket server: ``WebSocketServer.from_config(config,
  on_connection, radio=…)`` reads ``websockets.server.host`` /
  ``websockets.server.port`` / ``websockets.server.max_message_bytes``
  — all optional, defaults to ``0.0.0.0:8765`` with the library's
  message-size cap.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to placeholder constants below
(server bind defaults to ``0.0.0.0:8765`` from the library).

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example websockets circuitpython_server --device <id>
"""

import sys
import time

from chumicro_websockets import WebSocketServer
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack is absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying


def _load_runtime_config():
    """Return the deployed RuntimeConfig, or ``None`` when absent."""
    try:
        from chumicro_config import load_runtime_config
        return load_runtime_config()
    except (ImportError, OSError):
        return None


# ---------------------------------------------------------------------------
# Wifi up.
# ---------------------------------------------------------------------------

config = _load_runtime_config()
wifi_config = WifiConfig.try_from_config(config) if config is not None else None
if wifi_config is None:
    wifi_config = WifiConfig(
        ssid=WIFI_SSID,
        password=WIFI_PASSWORD,
        connect_timeout_ms=15_000,
    )

service = WifiService(wifi_config)


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _drive_until(predicate, deadline_ms):
    start = service._ticks_ms()  # noqa: SLF001
    while not predicate():
        now = service._ticks_ms()  # noqa: SLF001
        if service._ticks_diff(now, start) >= deadline_ms:  # noqa: SLF001
            return False
        if service.check(now):
            service.handle(now)
        time.sleep(0.05)
    return True


print(f"ADAPTER: {service.adapter_name}")
print("Connecting to wifi...")
if not _drive_until(lambda: service.state == WifiState.CONNECTED, 15_000):
    print("STATUS: FAIL_WIFI")
    print("ERROR:", service.last_error)
    raise SystemExit(1)
print(f"WIFI_OK ip={service.ip}")

wifi_radio = None
if sys.implementation.name == "circuitpython":
    radio_owner = getattr(service, "_adapter", None)
    wifi_radio = getattr(radio_owner, "_radio", None)
    if wifi_radio is None:
        import wifi as _wifi
        wifi_radio = _wifi.radio


# ---------------------------------------------------------------------------
# WebSocket server.
# ---------------------------------------------------------------------------


def on_connection(connection):
    print(f"[server] accept {connection.request_path}")
    connection.on_text = lambda text: (
        print(f"[server] recv: {text}"),
        connection.send_text(f"echo: {text}"),
    )
    connection.on_close = lambda code, reason: print(
        f"[server] closed code={code} reason={reason!r}",
    )


server = WebSocketServer.from_config(
    config if config is not None else {},
    on_connection,
    radio=wifi_radio,
)

# Resolve bound host/port for the status print (the listener owns
# them; we re-read the resolved config for display).
if config is not None:
    bound_host = config.get("websockets.server.host", "0.0.0.0")
    bound_port = config.get("websockets.server.port", 8765)
else:
    bound_host = "0.0.0.0"
    bound_port = 8765
print(f"[server] listening on {bound_host}:{bound_port}")

while True:
    if server.check(_now_ms()):
        server.handle(_now_ms())
    time.sleep(0.02)
