"""Board-side of the http_server_roundtrip demo.

Brings WiFi up with ``chumicro_wifi.WifiService`` and serves three
routes with ``chumicro_http_server.HttpServer``.  Both services
share one cooperative ``while True:`` loop (no async, no threads),
which is the same shape the README's "Give WiFi a deadline and keep
blinking" walkthrough uses.

The host driver discovers the board's address by reading the
``SERVER_READY ip=<ip> port=<port>`` marker line, fires three HTTP
requests, and the loop exits after the three matching ``ROUTE_HIT``
prints land and ``DEMO_COMPLETE`` is printed.
"""

import time

from chumicro_config import load_runtime_config
from chumicro_http_server import HttpServer, build_response
from chumicro_timing import Deadline, ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService

_DEMO_DEADLINE_MS = 60_000
_DEMO_ROUTES = ("/hello", "/uptime", "/echo")

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
server = HttpServer.from_config(config, radio=wifi.adapter.radio)
bind_port = config.get("http_server.bind_port", 8080)

hit_routes: list[str] = []
start_ticks_ms = ticks_ms()


@server.route("/hello")
def _hello(_request):
    hit_routes.append("/hello")
    print("ROUTE_HIT route=/hello")
    return build_response(
        200, json={"message": "hello from chumicro_http_server"},
    )


@server.route("/uptime")
def _uptime(_request):
    hit_routes.append("/uptime")
    uptime_ms = ticks_diff(ticks_ms(), start_ticks_ms)
    print(f"ROUTE_HIT route=/uptime uptime_ms={uptime_ms}")
    return build_response(200, json={"uptime_ms": uptime_ms})


@server.route("/echo", methods=["POST"])
def _echo(request):
    hit_routes.append("/echo")
    print("ROUTE_HIT route=/echo")
    return build_response(200, json={"echoed": request.json()})


ready_printed = False
deadline = Deadline(_DEMO_DEADLINE_MS, ticks_ms())

while len(hit_routes) < len(_DEMO_ROUTES):
    now_ms = ticks_ms()
    if deadline.expired(now_ms):
        print(
            f"DEMO_TIMEOUT hit={len(hit_routes)} "
            f"expected={len(_DEMO_ROUTES)}",
        )
        break

    if wifi.check(now_ms):
        wifi.handle(now_ms)

    if wifi.connected:
        # First server.handle() lazy-opens the listener, so SERVER_READY
        # only prints once the port is actually accepting connections.
        server.handle(now_ms)
        if not ready_printed:
            print(f"WIFI_OK ip={wifi.ip}")
            print(f"SERVER_READY ip={wifi.ip} port={bind_port}")
            ready_printed = True

    time.sleep(0.02)

server.close()
print("DEMO_COMPLETE")
