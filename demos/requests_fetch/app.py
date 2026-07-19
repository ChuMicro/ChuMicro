"""Board-side of the requests_fetch demo: one-shot HTTP GET via a generator.

``fetch_run`` expresses the whole lifecycle top-to-bottom: wait for the
wifi link with ``wait_for``, build the connector factory, then
``response = yield from get(transport_factory, url)`` driven by
``Runner.add_generator``.  One request, no polling a handle, no
``on_done`` callback; the ``Signal`` set from the wifi state-change
callback resumes the generator once the link is up.

Compare with ``libraries/requests/examples/periodic_get.py``, which
drives the long-lived ``HttpClient`` (``check`` / ``handle``) for
repeated requests on one client.  The generator form here is for a
one-shot fetch.

Marker lines (``WIFI_OK``, ``FETCHING``, ``FETCHED``, ``DEMO_COMPLETE``)
drive the host driver via stdout markers.
"""

from chumicro_config import load_runtime_config
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_test_harness.markers import marker
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState


def fetch_run(wifi, link_up, url):
    yield from wait_for(link_up)
    marker("WIFI_OK", ip=wifi.ip)
    factory = connector_factory(radio=wifi.adapter.radio)
    marker("FETCHING", url=url)
    response = yield from get(factory, url)
    marker("FETCHED", status=response.status_code, bytes=len(response.body))
    marker("DEMO_COMPLETE")


config = load_runtime_config()
fetch_url = config["requests.fetch.url"]

wifi = WifiService(WifiConfig.from_config(config))
runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))
runner.add(wifi)

link_up = Signal()


def signal_link_up(_old, new):
    if new == WifiState.CONNECTED:
        link_up.set(new)


wifi.on_state_change(signal_link_up)

fetch_handle = runner.add_generator(fetch_run(wifi, link_up, fetch_url))
runner.run_until(fetch_handle)
