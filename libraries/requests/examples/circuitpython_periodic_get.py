"""Periodic HTTP GET on a real CircuitPython / MicroPython board.

Brings wifi up, fetches a configured URL every ``POLL_INTERVAL_S``
seconds, prints the status code + body length.  Demonstrates the
runner-shaped client driving real network I/O while a simple
LED-style counter keeps incrementing — proof that the in-flight
request never block-calls the loop.

WiFi config comes from the standard chumicro pipeline:
:func:`chumicro_config.load_runtime_config` reads
``/runtime_config.msgpack`` (baked from workspace.yml at deploy
time by ``chumicro-workspace``).  The ``[wifi]`` section feeds
:class:`chumicro_wifi.WifiConfig`.  Falls back to the
``WIFI_SSID`` / ``WIFI_PASSWORD`` constants below for raw
single-file deploys without a workspace.

Target URL similarly: reads ``[periodic_get].url`` from
``runtime_config.msgpack`` if present, else uses the ``TARGET_URL``
constant below.

Deploying
=========

Recommended (workspace-managed)::

    chumicro-workspace deploy periodic_get

Raw (single-file copy)::

    1. Edit WIFI_SSID, WIFI_PASSWORD, TARGET_URL below.
    2. Copy this file as ``/code.py`` (CP) or ``/main.py`` (MP).
    3. Ensure chumicro-{wifi,sockets,requests,config,timing,runner,
       msgpack} are present under ``/lib/``.

Example output::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    Polling http://example.com/ every 30 s
    [1] status=200 bytes=1256 led_ticks=87
    [2] status=200 bytes=1256 led_ticks=89
"""

import sys
import time

from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
TARGET_URL = "http://example.com/"
POLL_INTERVAL_S = 30
REQUEST_TIMEOUT_MS = 8_000


def _load_runtime_settings():
    """Return ``(wifi_config, target_url)`` from runtime_config or fallbacks."""
    wifi_config = None
    target_url = TARGET_URL
    try:
        from chumicro_config import load_runtime_config

        config = load_runtime_config()
        if config:
            wifi_section = config.get("wifi")
            if wifi_section:
                wifi_config = WifiConfig.from_dict(wifi_section)
            poll_section = config.get("periodic_get", {})
            target_url = poll_section.get("url", target_url)
    except (ImportError, OSError):
        pass
    if wifi_config is None:
        wifi_config = WifiConfig(
            ssid=WIFI_SSID,
            password=WIFI_PASSWORD,
            connect_timeout_ms=15_000,
        )
    return wifi_config, target_url


# ---------------------------------------------------------------------------
# Wifi up.
# ---------------------------------------------------------------------------

wifi_config, target_url = _load_runtime_settings()
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
# HTTP client + poll loop.
# ---------------------------------------------------------------------------

client = HttpClient(
    connection_factory=chumicro_sockets_factory(radio=wifi_radio),
    default_timeout_ms=REQUEST_TIMEOUT_MS,
)

print(f"Polling {target_url} every {POLL_INTERVAL_S} s")

attempt = 0

while True:
    attempt += 1
    request = client.get(target_url)
    led_counter = 0

    while not request.done:
        now = service._ticks_ms()  # noqa: SLF001
        if service.check(now):
            service.handle(now)
        if client.check(now):
            client.handle(now)
        led_counter += 1
        time.sleep(0.02)

    if request.error is not None:
        print(f"[{attempt}] ERROR={request.error!r}")
    else:
        response = request.result
        print(
            f"[{attempt}] status={response.status_code} "
            f"bytes={len(response.body)} led_ticks={led_counter}",
        )

    # Wait for the next interval — keep ticking wifi so
    # reconnects work in the gap.
    next_at = time.monotonic() + POLL_INTERVAL_S
    while time.monotonic() < next_at:
        now = service._ticks_ms()  # noqa: SLF001
        if service.check(now):
            service.handle(now)
        time.sleep(0.05)
