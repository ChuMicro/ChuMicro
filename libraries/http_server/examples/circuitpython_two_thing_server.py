"""Two-thing demo — display server side.

Pairs with ``two_thing_sensor.py`` running on a separate board.  This
side opens an HTTP server on port 8080 with three routes:

* ``GET /`` — HTML status page showing the latest reading.
* ``GET /api/latest`` — JSON ``{"value": <last>, "received_at": <ms>}``.
* ``POST /api/sensor`` — accepts JSON ``{"sensor_id": str, "value": Number}``,
  stores the latest value, returns 201.

Architecture (Decision 0014 + Decision 0041):

* Single-process, runner-shaped: the LED keeps blinking while the
  server is mid-handshake / mid-response thanks to the per-tick
  ``server.handle()`` cooperative dispatch.
* In-memory state: latest reading lives in a ``_State`` dataclass.
  No persistence — power cycle clears.

Run on a board (CircuitPython or MicroPython) configured with WiFi
via ``chumicro-workspace``:

    chumicro-workspace deploy --thing two_thing_server

Or copy this single file as ``main.py`` / ``code.py`` after the
``chumicro-{wifi,sockets,http_server}`` libraries land at ``/lib``.

Example output (server side stdout)::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    Server listening on port 8080.  Hit http://10.0.0.42:8080/
    [+] sensor=temp value=72.5
    [+] sensor=temp value=72.7
"""

import sys
import time

from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import tcp_listening_socket
from chumicro_wifi import WifiConfig, WifiService, WifiState

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying
LISTEN_PORT = 8080


class _State:
    """Latest sensor reading."""

    __slots__ = ("received_at_ms", "sensor_id", "value")

    def __init__(self):
        self.sensor_id = None
        self.value = None
        self.received_at_ms = None


state = _State()


def _now_ms():
    """Return wall-clock-ish ms via ``time.monotonic`` (cross-runtime)."""
    try:
        return int(time.monotonic_ns() // 1_000_000)
    except AttributeError:
        return int(time.monotonic() * 1000)


# ---------------------------------------------------------------------------
# Wifi up.  See chumicro-wifi docs for production-grade reconnect.
# ---------------------------------------------------------------------------

config = WifiConfig(
    ssid=WIFI_SSID, password=WIFI_PASSWORD, connect_timeout_ms=15_000,
)
service = WifiService(config)


def _drive_until(predicate, deadline_ms):
    start = service._ticks_ms()  # noqa: SLF001 — example uses internal clock
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
# Server.
# ---------------------------------------------------------------------------

server = HttpServer(
    listener_factory=lambda: tcp_listening_socket(
        "0.0.0.0", LISTEN_PORT, radio=wifi_radio,
    ),
    max_connections=2,
)


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


print(f"Server listening on port {LISTEN_PORT}.  Hit http://{service.ip}:{LISTEN_PORT}/")

while True:
    now = service._ticks_ms()  # noqa: SLF001
    if service.check(now):
        service.handle(now)
    if server.check(now):
        server.handle(now)
    time.sleep(0.02)
