"""NTPClient on CircuitPython — query a real NTP server over wifi.

Brings wifi up via ``chumicro-wifi``, builds an ``NTPClient`` via
``NTPClient.from_config`` (which auto-constructs a UDP socket through
``chumicro-sockets``), and runs one SNTP query.  The result's
Unix-epoch seconds value should be a recent timestamp (~1.7B as of
2026).

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi: ``WifiConfig.try_from_config(config)`` reads ``wifi.ssid`` /
  ``wifi.password`` plus optional tunables.
* NTP: ``NTPClient.from_config(config, radio=…)`` reads
  ``ntp.server`` / ``ntp.port`` / ``ntp.timeout_ms`` — all optional
  with sensible defaults (``pool.ntp.org``, port 123, 5 s timeout).

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to the placeholder constants below
— edit them first.  NTP server / port / timeout fall through to
``NTPClient.from_config``'s built-in defaults; no edits required.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example ntp circuitpython_ntp_query --device <id>

The deploy composes ``secrets.toml`` + ``examples/config.toml`` into
the staged ``runtime_config.msgpack`` before deploying.

Example output::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    NTP_OK unix_seconds=1745782634
"""

import sys
import time

from chumicro_ntp import NTPClient
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
# NTP query.
# ---------------------------------------------------------------------------

ntp_config = config if config is not None else {}
client = NTPClient.from_config(ntp_config, radio=wifi_radio)


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


request = client.query()
while not request.done:
    if client.check(_now_ms()):
        client.handle(_now_ms())
    time.sleep(0.02)

if request.error is not None:
    print(f"NTP_FAIL {request.error}")
    raise SystemExit(1)

print(f"NTP_OK unix_seconds={request.unix_seconds}")

client.socket.close()
