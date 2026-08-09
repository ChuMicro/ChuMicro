"""Board-side of the http_server_roundtrip demo.

Brings WiFi up with ``chumicro_wifi.WifiService`` and serves three
routes with ``chumicro_http_server.HttpServer``.  Both services
register with one ``chumicro_runner.Runner`` and the loop is a single
``runner.run_until(...)`` call with a deadline.

The host driver discovers the board's address by reading the
``SERVER_READY ip=<ip> port=<port>`` marker line, fires three HTTP
requests, and the loop exits after the three matching ``ROUTE_HIT``
markers land and ``DEMO_COMPLETE`` is printed.
"""

from chumicro_config import load_runtime_config
from chumicro_http_server import HttpServer, build_response
from chumicro_runner import Runner
from chumicro_test_harness.markers import marker
from chumicro_timing import ticks_diff, ticks_ms
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
    marker("ROUTE_HIT", route="/hello")
    return build_response(
        200, json={"message": "hello from chumicro_http_server"},
    )


@server.route("/uptime")
def _uptime(_request):
    hit_routes.append("/uptime")
    uptime_ms = ticks_diff(ticks_ms(), start_ticks_ms)
    marker("ROUTE_HIT", route="/uptime", uptime_ms=uptime_ms)
    return build_response(200, json={"uptime_ms": uptime_ms})


@server.route("/echo", methods=["POST"])
def _echo(request):
    hit_routes.append("/echo")
    marker("ROUTE_HIT", route="/echo")
    return build_response(200, json={"echoed": request.json()})


runner = Runner()
runner.add(wifi)

demo_state = {"server_registered": False, "announced": False}


def bring_up_server(now_ms):
    # Register the server only once the link is up (its listener binds on
    # the radio), then announce once the first handle() has opened the port.
    if not demo_state["server_registered"]:
        if not wifi.connected:
            return
        runner.add(server)
        demo_state["server_registered"] = True
        return
    if not demo_state["announced"] and server.io_socket is not None:
        marker("WIFI_OK", ip=wifi.ip)
        marker("SERVER_READY", ip=wifi.ip, port=bind_port)
        demo_state["announced"] = True


runner.add(handler=bring_up_server)

completed = runner.run_until(
    lambda: len(hit_routes) >= len(_DEMO_ROUTES),
    timeout_ms=_DEMO_DEADLINE_MS,
)
if not completed:
    marker(
        "DEMO_TIMEOUT",
        hit=len(hit_routes),
        expected=len(_DEMO_ROUTES),
    )

server.close()
marker("DEMO_COMPLETE")
