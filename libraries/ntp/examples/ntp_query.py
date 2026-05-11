"""NTPClient on CircuitPython / MicroPython — query a real NTP server.

Brings wifi up via the local ``helpers`` module, builds an
``NTPClient`` via ``NTPClient.from_config`` (which auto-constructs a
UDP socket through ``chumicro-sockets``), and runs one SNTP query.
The result's Unix-epoch seconds value should be a recent timestamp
(~1.7B as of 2026).

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* NTP (read by ``NTPClient.from_config``): ``ntp.server`` /
  ``ntp.port`` / ``ntp.timeout_ms`` — all optional with sensible
  defaults (``pool.ntp.org``, port 123, 5 s timeout).

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to the placeholder constants below
— edit them first.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example ntp ntp_query --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    NTP_OK unix_seconds=1745782634
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the SNTP client itself
#: is pure-Python.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_ntp import NTPClient
from helpers import runtime_config, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

client = NTPClient.from_config(config, radio=radio)

request = client.query()
while not request.done:
    if client.check(ticks_ms()):
        client.handle(ticks_ms())
    time.sleep(0.02)

if request.error is not None:
    print(f"NTP_FAIL {request.error}")
    raise SystemExit(1)

print(f"NTP_OK unix_seconds={request.unix_seconds}")

client.socket.close()
