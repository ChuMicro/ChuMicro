"""Two-thing demo — sensor side.

Pairs with ``two_thing_server.py`` running on a different board.
This side reads a "sensor" value (we use a synthetic sine-wave
since this example doesn't assume a real sensor on the board) and
POSTs it to the server's ``/api/sensor`` endpoint every 5 seconds.

Architecture (Decision 0014 + Decision 0040):

* Single-process, runner-shaped: ``HttpClient.check`` /
  ``HttpClient.handle`` advance the in-flight POST one tick at a
  time, so an LED can keep blinking through the request.  Same
  shape as ``chumicro-mqtt``.
* No persistence — restart starts the synthetic sensor's clock at 0.

Replace ``SERVER_HOST`` with the IP of the board running
``two_thing_server.py`` (which prints its IP at startup).

Example output::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.43
    Posting to http://10.0.0.42:8080/api/sensor every 5 s
    [+] POST attempt=1 status=201
    [+] POST attempt=2 status=201
"""

import math
import sys
import time

from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_wifi import WifiConfig, WifiService, WifiState

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
SERVER_HOST = "10.0.0.42"  # replace with the server-thing's IP
SERVER_PORT = 8080
SENSOR_ID = "demo-temp"
POST_INTERVAL_S = 5


# ---------------------------------------------------------------------------
# Wifi up.
# ---------------------------------------------------------------------------

config = WifiConfig(
    ssid=WIFI_SSID, password=WIFI_PASSWORD, connect_timeout_ms=15_000,
)
service = WifiService(config)


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
# HTTP client.
# ---------------------------------------------------------------------------

client = HttpClient(
    connection_factory=chumicro_sockets_factory(radio=wifi_radio),
    default_timeout_ms=8_000,
)
url = f"http://{SERVER_HOST}:{SERVER_PORT}/api/sensor"

print(f"Posting to {url} every {POST_INTERVAL_S} s")


def _synthetic_reading(elapsed_seconds: float) -> float:
    """A made-up reading that varies smoothly over time.

    Replace this with a real sensor read on a board that has one
    (e.g. a thermistor, BME280, etc.).
    """
    return round(20.0 + 5.0 * math.sin(elapsed_seconds / 30.0), 2)


# ---------------------------------------------------------------------------
# Main loop — issue one POST per interval, drive client between ticks.
# ---------------------------------------------------------------------------

attempt = 0
start_seconds = time.monotonic()

while True:
    attempt += 1
    elapsed = time.monotonic() - start_seconds
    payload = {
        "sensor_id": SENSOR_ID,
        "value": _synthetic_reading(elapsed),
        "uptime_s": round(elapsed, 1),
    }
    handle = client.get  # placeholder so the linter doesn't complain — replaced below
    handle = client.post(url, json=payload)
    while not handle.done:
        now = service._ticks_ms()  # noqa: SLF001
        if service.check(now):
            service.handle(now)
        if client.check(now):
            client.handle(now)
        time.sleep(0.02)

    if handle.error is not None:
        print(f"[!] POST attempt={attempt} ERROR={handle.error!r}")
    else:
        response = handle.result
        print(f"[+] POST attempt={attempt} status={response.status_code}")

    # Wait for the next interval (cooperative — runner ticks too).
    next_at = time.monotonic() + POST_INTERVAL_S
    while time.monotonic() < next_at:
        now = service._ticks_ms()  # noqa: SLF001
        if service.check(now):
            service.handle(now)
        time.sleep(0.05)
