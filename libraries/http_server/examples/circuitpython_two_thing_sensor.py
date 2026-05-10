"""Two-thing demo — sensor side.

Pairs with ``circuitpython_two_thing_server.py`` running on a
different board.  This side reads a "sensor" value (we use a synthetic
sine-wave since this example doesn't assume a real sensor on the
board) and POSTs it to the server's ``/api/sensor`` endpoint every 5
seconds.

Architecture:

* Single-process, runner-shaped: ``HttpClient.check`` /
  ``HttpClient.handle`` advance the in-flight POST one tick at a
  time, so an LED can keep blinking through the request.  Same
  shape as ``chumicro-mqtt``.
* No persistence — restart starts the synthetic sensor's clock at 0.

Note: this is a server-side example for ``chumicro-http-server``,
but the *client* in this pair is built from ``chumicro_requests`` —
which the http_server library declares (transitively, through
``chumicro-sockets``) as available on a board running its examples.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* HTTP client (read by ``HttpClient.from_config``):
  ``requests.default_timeout_ms`` etc. — all optional, library defaults.
* App-level: ``two_thing_sensor.server_host`` / ``server_port`` /
  ``sensor_id``.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), the constants below are used as fallbacks — replace
``SERVER_HOST`` with the IP of the board running
``circuitpython_two_thing_server.py`` (it prints its IP at startup).

Example output::

    WIFI_OK ip=10.0.0.43
    Posting to http://10.0.0.42:8080/api/sensor every 5 s
    [+] POST attempt=1 status=201
    [+] POST attempt=2 status=201
"""

import math
import time

from chumicro_requests import HttpClient
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
SERVER_HOST = "10.0.0.42"  # replace with the server-thing's IP
SERVER_PORT = 8080
SENSOR_ID = "demo-temp"
POST_INTERVAL_S = 5

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

server_host = config.get("two_thing_sensor.server_host", SERVER_HOST)
server_port = config.get("two_thing_sensor.server_port", SERVER_PORT)
sensor_id = config.get("two_thing_sensor.sensor_id", SENSOR_ID)

client = HttpClient.from_config(config, radio=radio)
url = f"http://{server_host}:{server_port}/api/sensor"

print(f"Posting to {url} every {POST_INTERVAL_S} s")


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _synthetic_reading(elapsed_seconds: float) -> float:
    """Synthetic sine-wave reading; replace with your real sensor."""
    return round(20.0 + 5.0 * math.sin(elapsed_seconds / 30.0), 2)


attempt = 0
start_seconds = time.monotonic()

while True:
    attempt += 1
    elapsed = time.monotonic() - start_seconds
    payload = {
        "sensor_id": sensor_id,
        "value": _synthetic_reading(elapsed),
        "uptime_s": round(elapsed, 1),
    }
    handle = client.post(url, json=payload)
    while not handle.done:
        if client.check(_now_ms()):
            client.handle(_now_ms())
        time.sleep(0.02)

    if handle.error is not None:
        print(f"[!] POST attempt={attempt} ERROR={handle.error!r}")
    else:
        response = handle.result
        print(f"[+] POST attempt={attempt} status={response.status_code}")

    next_at = time.monotonic() + POST_INTERVAL_S
    while time.monotonic() < next_at:
        time.sleep(0.05)
