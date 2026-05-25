"""Board-side of the http_server_roundtrip demo.

Brings wifi up, starts an HttpServer with a couple of demo routes,
prints ``SERVER_READY ip=<ip> port=<port>`` once accepting, ticks the
server cooperatively until the host driver has hit every advertised
route or the deadline expires.  Marker lines (``SERVER_READY``,
``ROUTE_HIT``, ``DEMO_COMPLETE``) drive the host driver via the
stdout-marker protocol.

Cross-runtime — pure-Python HttpServer + chumicro_sockets +
chumicro_test_harness.network for wifi-up.  No CP / MP branching in
this file; the test harness handles the per-runtime wifi glue.
"""

import time

from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import tcp_listening_socket
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_diff, ticks_ms

_LISTEN_PORT = 8765
_DEMO_DEADLINE_MS = 60_000
_TICK_SLEEP_MS = 20

#: Each route the demo advertises.  When all three have been hit the
#: loop exits and the board prints ``DEMO_COMPLETE``.  Adding a route
#: here is enough to extend the demo; the driver reads the marker
#: stream so it doesn't need to know the route list up front.
_DEMO_ROUTES = ("/hello", "/uptime", "/echo")


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


config = runtime_config()
radio, ip_address = wifi_up(
    config.get("wifi.ssid"),
    config.get("wifi.password"),
)
print(f"WIFI_OK ip={ip_address}")

server = HttpServer(
    listener_factory=lambda: tcp_listening_socket(
        host="0.0.0.0", port=_LISTEN_PORT, radio=radio,
    ),
)

hit_routes: list[str] = []
start_ticks_ms = ticks_ms()


@server.route("/hello")
def _hello_route(request):  # noqa: ARG001
    hit_routes.append("/hello")
    print("ROUTE_HIT route=/hello")
    return build_response(
        200, json={"message": "hello from chumicro_http_server"},
    )


@server.route("/uptime")
def _uptime_route(request):  # noqa: ARG001
    hit_routes.append("/uptime")
    uptime_ms = ticks_diff(ticks_ms(), start_ticks_ms)
    print(f"ROUTE_HIT route=/uptime uptime_ms={uptime_ms}")
    return build_response(200, json={"uptime_ms": uptime_ms})


@server.route("/echo", methods=["POST"])
def _echo_route(request):
    hit_routes.append("/echo")
    payload = request.json()
    print(f"ROUTE_HIT route=/echo")
    return build_response(200, json={"echoed": payload})


# One tick to bind the listener + initialize the accept loop.
server.handle(ticks_ms())
print(f"SERVER_READY ip={ip_address} port={_LISTEN_PORT}")

deadline = ticks_ms() + _DEMO_DEADLINE_MS
while len(hit_routes) < len(_DEMO_ROUTES):
    now = ticks_ms()
    if ticks_diff(deadline, now) <= 0:
        print(
            f"DEMO_TIMEOUT hit={len(hit_routes)} expected={len(_DEMO_ROUTES)}",
        )
        break
    if server.check(now):
        server.handle(now)
    _sleep_ms(_TICK_SLEEP_MS)

server.close()
print("DEMO_COMPLETE")
