"""Periodic HTTP GET on a real CircuitPython / MicroPython board.

Brings wifi up via the local ``helpers`` module, fetches a configured
URL every ``POLL_INTERVAL_S`` seconds, prints the status code + body
length.  Demonstrates the runner-shaped client driving real network
I/O while a simple LED-style counter keeps incrementing — proof that
the in-flight request never block-calls the loop.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* HTTP (read by ``HttpClient.from_config``): ``requests.default_timeout_ms``
  / ``requests.default_max_redirects`` / ``requests.user_agent`` /
  ``requests.max_body_bytes`` — all optional with library defaults.
* App-level (this example's own concerns, not the library's):
  ``periodic_get.url``.

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds and the target URL fall back to the placeholder
constants below — edit them first.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example requests periodic_get --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    Polling http://example.com/ every 30 s
    [1] status=200 bytes=1256 led_ticks=87
    [2] status=200 bytes=1256 led_ticks=89
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the HTTP client is
#: pure-Python.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_requests import HttpClient
from helpers import runtime_config, ticks_add, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
TARGET_URL = "http://example.com/"
POLL_INTERVAL_S = 30

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

target_url = config.get("periodic_get.url", TARGET_URL)
client = HttpClient.from_config(config, radio=radio)
print(f"Polling {target_url} every {POLL_INTERVAL_S} s")


attempt = 0
while True:
    attempt += 1
    request = client.get(target_url)
    led_counter = 0
    while not request.done:
        if client.check(ticks_ms()):
            client.handle(ticks_ms())
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

    next_due = ticks_add(ticks_ms(), POLL_INTERVAL_S * 1000)
    while ticks_diff(next_due, ticks_ms()) > 0:
        time.sleep(0.05)
