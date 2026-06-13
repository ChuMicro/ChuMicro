"""Board-side of the requests_fetch demo — one-shot HTTP GET via a generator.

Brings wifi up with ``chumicro_wifi.WifiService``, then a generator
does ``response = yield from get(connector_factory, url)`` driven by
``Runner.add_generator``.  One request, written top-to-bottom: connect,
send, receive, return the response — no polling a handle, no ``on_done``
callback.

Compare with ``libraries/requests/examples/periodic_get.py``, which
drives the long-lived ``HttpClient`` (``check`` / ``handle``) for
repeated requests on one client.  The generator form here is for a
one-shot fetch.

Marker lines (``WIFI_OK``, ``FETCHING``, ``FETCHED``, ``DEMO_COMPLETE``)
drive the host driver via stdout markers.
"""

from chumicro_config import load_runtime_config
from chumicro_requests.generators import get
from chumicro_requests.sockets_factory import chumicro_sockets_connector_factory
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService, WifiState

config = load_runtime_config()
fetch_url = config["requests.fetch.url"]

wifi = WifiService(WifiConfig.from_config(config))
runner = Runner()
runner.add(wifi)

fetch_handle = None


def fetch_run(connector_factory, url):
    print(f"FETCHING url={url}")
    response = yield from get(connector_factory, url)
    print(f"FETCHED status={response.status_code} bytes={len(response.body)}")
    print("DEMO_COMPLETE")


def on_wifi_state(_old, new):
    global fetch_handle  # noqa: PLW0603
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        factory = chumicro_sockets_connector_factory(radio=wifi.adapter.radio)
        fetch_handle = runner.add_generator(fetch_run(factory, url=fetch_url))


wifi.on_state_change(on_wifi_state)

while fetch_handle is None or not fetch_handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
