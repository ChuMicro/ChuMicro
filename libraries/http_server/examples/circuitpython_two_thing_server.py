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

* WiFi: ``WifiConfig.try_from_config(config)`` reads ``wifi.ssid`` /
  ``wifi.password``.
* HTTP server: ``HttpServer.from_config(config, radio=…)`` reads
  ``http_server.bind_host`` / ``bind_port`` / ``max_connections`` /
  ``request_timeout_ms`` / ``max_request_body_bytes`` plus the
  optional TLS pair ``http_server.tls.cert_path`` /
  ``http_server.tls.key_path``.  All optional with library defaults
  (``0.0.0.0:8080``, plain TCP listener).

When ``runtime_config.msgpack`` isn't present (raw single-file
deploys), wifi creds fall back to the placeholder constants below
— edit them first.  Server bind defaults to ``0.0.0.0:8080``.

Deploying
=========

Deploy with ``chumicro-workspace``::

    chumicro-workspace deploy-example http_server circuitpython_two_thing_server --device <id>

Example output (server side stdout)::

    ADAPTER: cp
    WIFI_OK ip=10.0.0.42
    Server listening on 0.0.0.0:8080.  Hit http://10.0.0.42:8080/
    [+] sensor=temp value=72.5
"""

import sys
import time

from chumicro_http_server import HttpServer, build_response
from chumicro_wifi import WifiConfig, WifiService, WifiState

# Fallback constants — used only when runtime_config.msgpack is absent.
WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying


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


def _now_ms():
    """Wall-clock-ish ms via ``time.monotonic`` (cross-runtime)."""
    try:
        return int(time.monotonic_ns() // 1_000_000)
    except AttributeError:
        return int(time.monotonic() * 1000)


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
# Server.
# ---------------------------------------------------------------------------


class _State:
    """Latest sensor reading."""

    __slots__ = ("received_at_ms", "sensor_id", "value")

    # Annotations widen the inferred Optional types — `__init__` binds
    # `None` initially, the `/api/sensor` handler later writes an `int` /
    # `str` / `float`.  Annotations are stripped at compile time on
    # CircuitPython and MicroPython, so this carries zero runtime cost.
    received_at_ms: int | None
    sensor_id: str | None
    value: float | None

    def __init__(self):
        self.sensor_id = None
        self.value = None
        self.received_at_ms = None


state = _State()

server = HttpServer.from_config(
    config if config is not None else {},
    radio=wifi_radio,
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


# Resolve bound host/port for the status print (the listener owns
# them; we re-read the resolved config for display).
if config is not None:
    bound_host = config.get("http_server.bind_host", "0.0.0.0")
    bound_port = config.get("http_server.bind_port", 8080)
else:
    bound_host = "0.0.0.0"
    bound_port = 8080
print(
    f"Server listening on {bound_host}:{bound_port}.  "
    f"Hit http://{service.ip}:{bound_port}/",
)

while True:
    now = service._ticks_ms()  # noqa: SLF001
    if service.check(now):
        service.handle(now)
    if server.check(now):
        server.handle(now)
    time.sleep(0.02)
