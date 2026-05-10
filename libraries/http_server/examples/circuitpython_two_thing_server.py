"""Two-thing demo — display server side.

Pairs with ``circuitpython_two_thing_sensor.py`` running on a
separate board.  This side opens an HTTP server with three routes:

* ``GET /`` — HTML status page showing the latest reading.
* ``GET /api/latest`` — JSON ``{"value": <last>, "received_at": <ms>}``.
* ``POST /api/sensor`` — accepts JSON ``{"sensor_id": str, "value": Number}``,
  stores the latest value, returns 201.

Architecture: single-process, runner-shaped (LED keeps blinking
through accept / dispatch / response thanks to the per-tick
``server.handle()`` cooperative dispatch).  In-memory state — no
persistence.

Configuration
=============

Reads the deployed ``runtime_config.msgpack`` (baked from
``secrets.toml`` + per-example ``examples/config.toml`` by the
deploy pipeline) via the flat-key API:

* WiFi (read by ``helpers.wifi_up``): ``wifi.ssid`` / ``wifi.password``.
* HTTP server (read by ``HttpServer.from_config``):
  ``http_server.bind_host`` / ``bind_port`` / ``max_connections`` /
  ``request_timeout_ms`` / ``max_request_body_bytes`` plus the optional
  TLS pair ``http_server.tls.cert_path`` / ``http_server.tls.key_path``.
  All optional with library defaults (``0.0.0.0:8080``, plain TCP listener).

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to the placeholder constants below
— edit them first.  Server bind defaults to ``0.0.0.0:8080``.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example http_server circuitpython_two_thing_server --device <id>

Example output (server side stdout)::

    WIFI_OK ip=10.0.0.42
    Server listening on 0.0.0.0:8080.  Hit http://10.0.0.42:8080/
    [+] sensor=temp value=72.5
"""

import time

from chumicro_http_server import HttpServer, build_response
from helpers import runtime_config, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")


def _now_ms():
    """Wall-clock-ish ms via ``time.monotonic`` (cross-runtime)."""
    try:
        return int(time.monotonic_ns() // 1_000_000)
    except AttributeError:
        return int(time.monotonic() * 1000)


class _State:
    """Latest sensor reading."""

    __slots__ = ("received_at_ms", "sensor_id", "value")

    received_at_ms: int | None
    sensor_id: str | None
    value: float | None

    def __init__(self):
        self.sensor_id = None
        self.value = None
        self.received_at_ms = None


state = _State()

server = HttpServer.from_config(config, radio=radio)


@server.route("/")
def index(request):
    """Status page with the latest reading."""
    if state.value is None:
        body_html = (
            "<html><body><h1>chumicro two-thing demo</h1>"
            "<p>No readings yet — waiting for sensor POST.</p>"
            "</body></html>"
        )
    else:
        body_html = (
            "<html><body><h1>chumicro two-thing demo</h1>"
            f"<p>Latest from <b>{state.sensor_id}</b>:"
            f" <b>{state.value}</b></p>"
            f"<p>Received at: {state.received_at_ms} ms</p>"
            "</body></html>"
        )
    return build_response(200, html=body_html)


@server.route("/api/latest")
def latest(request):
    """JSON view of the latest reading."""
    return build_response(200, json={
        "sensor_id": state.sensor_id,
        "value": state.value,
        "received_at_ms": state.received_at_ms,
    })


@server.route("/api/sensor", methods=["POST"])
def sensor(request):
    """Accept a sensor reading + update state."""
    payload = request.json()
    state.sensor_id = payload.get("sensor_id", "unknown")
    state.value = payload.get("value")
    state.received_at_ms = _now_ms()
    print(f"[+] sensor={state.sensor_id} value={state.value}")
    return build_response(201, json={"ok": True})


bound_host = config.get("http_server.bind_host", "0.0.0.0")
bound_port = config.get("http_server.bind_port", 8080)
print(f"Server listening on {bound_host}:{bound_port}.  Hit http://{ip}:{bound_port}/")

while True:
    if server.check(_now_ms()):
        server.handle(_now_ms())
    time.sleep(0.02)
