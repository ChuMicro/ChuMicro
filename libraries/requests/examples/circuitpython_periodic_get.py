"""Periodic HTTP GET on a real CircuitPython / MicroPython board.

Brings wifi up, fetches a configured URL every ``POLL_INTERVAL_S``
seconds, prints the status code + body length.  Demonstrates the
runner-shaped client driving real network I/O while a simple
LED-style counter keeps incrementing — proof that the in-flight
request never block-calls the loop.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi: ``WifiConfig.try_from_config(config)`` reads ``wifi.ssid`` /
  ``wifi.password`` plus optional tunables.
* HTTP: ``HttpClient.from_config(config, radio=…)`` reads
  ``requests.default_timeout_ms`` / ``requests.default_max_redirects``
  / ``requests.user_agent`` / ``requests.max_body_bytes`` — all
  optional with library defaults.
* App-level (this example's own concerns, not the library's):
  ``periodic_get.url``.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds and the target URL fall back to the
placeholder constants below — edit them first.

Deploying
=========

Deploy from a chumicro fork or clone::

    python scripts/run.py deploy-example requests circuitpython_periodic_get --device <id>

Or from a workspace template repo (for user-authored projects
that follow the same example shape).  Either path composes
``secrets.toml`` + ``examples/config.toml`` into the staged
``runtime_config.msgpack`` before deploying.

Example output::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    Polling http://example.com/ every 30 s
    [1] status=200 bytes=1256 led_ticks=87
    [2] status=200 bytes=1256 led_ticks=89
"""

import sys
import time

from chumicro_requests import HttpClient
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack is absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
TARGET_URL = "http://example.com/"
POLL_INTERVAL_S = 30


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
# HTTP client + poll loop.
# ---------------------------------------------------------------------------

# App-level setting (not in requests' library manifest).
target_url = (
    config.get("periodic_get.url", TARGET_URL)
    if config is not None
    else TARGET_URL
)

client = HttpClient.from_config(
    config if config is not None else {},
    radio=wifi_radio,
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
