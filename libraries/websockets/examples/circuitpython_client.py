"""WebSocket client demo for CircuitPython / MicroPython boards.

Connects to a configured echo server and prints every message the
server sends back.  Drives the client from a hand-rolled tick loop
so an LED can keep blinking through the handshake, frame I/O, and
the close handshake.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi: ``WifiConfig.try_from_config(config)`` reads ``wifi.ssid`` /
  ``wifi.password`` plus optional tunables.
* WebSocket client: ``WebSocketClient.from_config(config, radio=…)``
  reads ``websockets.client.max_message_bytes`` (optional, library
  default).
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

    chumicro-workspace deploy-example websockets circuitpython_client --device <id>
"""

import sys
import time

from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack is absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
WS_URL = "ws://192.168.1.42:8765/echo"


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
# WebSocket client + ping/echo loop.
# ---------------------------------------------------------------------------

# App-level: the URL is per-connection.  It's declared in the manifest
# so users know where to put it, but `from_config` doesn't read it.
connect_url = (
    config.get("websockets.client.connect_url", WS_URL)
    if config is not None
    else WS_URL
)

client = WebSocketClient.from_config(
    config if config is not None else {},
    radio=wifi_radio,
)
client.on_open = lambda: print("[client] open")
client.on_text = lambda text: print(f"[client] received: {text}")
client.on_close = lambda code, reason: print(
    f"[client] closed code={code} reason={reason!r}",
)

client.connect(connect_url, timeout_ms=10_000)

sent_count = 0
while client.state != WebSocketState.CLOSED:
    if client.check(_now_ms()):
        client.handle(_now_ms())
    if client.state == WebSocketState.OPEN and sent_count < 3:
        client.send_text(f"ping {sent_count}")
        sent_count += 1
        if sent_count == 3:
            client.close()
