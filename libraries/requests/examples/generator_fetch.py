"""One-shot HTTP GET as a generator on a real CircuitPython / MicroPython board.

Brings wifi up via the local ``helpers`` module, then fetches a URL
with a single ``response = yield from get(...)`` driven by
``Runner.add_generator``.  The request reads top-to-bottom — connect,
send, receive, return — with no handle to poll and no ``on_done``
callback.

Pair with ``periodic_get.py``, which drives the long-lived ``HttpClient``
(``check`` / ``handle``) for repeated requests on one client; the
generator form here is for a one-shot fetch.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the deploy
pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* App-level: ``generator_fetch.url`` (the URL to fetch).

When ``runtime_config.msgpack`` isn't present, wifi creds and the URL
fall back to the placeholder constants below — edit them first.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example requests generator_fetch --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    Fetching http://example.com/
    status=200 bytes=1256
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP); the generator is pure-Python.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
TARGET_URL = "http://example.com/"

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

target_url = config.get("generator_fetch.url", TARGET_URL)
transport_factory = connector_factory(radio=radio)
print(f"Fetching {target_url}")


def fetch_once():
    response = yield from get(transport_factory, target_url)
    print(f"status={response.status_code} bytes={len(response.body)}")


runner = Runner()
handle = runner.add_generator(fetch_once())
while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
