"""Simple HTTP server on CircuitPython / MicroPython.

Brings wifi up via the local ``helpers`` module, opens an HTTP server
on ``0.0.0.0:8080`` with three routes, and prints requests as they
arrive.  Single-board demo — drive it from your laptop with ``curl``
or a browser; for a two-physical-board pattern see the
``two_board_handshake/`` example in the workspace template.

Routes:

* ``GET /`` — HTML hello page (open in a browser).
* ``GET /api/uptime`` — JSON ``{"uptime_ms": <int>}``; updates between
  hits so you can see the server is live.
* ``POST /api/echo`` — accepts any JSON body, returns it wrapped as
  ``{"echoed": <body>}``.

Configuration
=============

Reads ``/runtime_config.msgpack`` via ``helpers.runtime_config()``:

* WiFi: ``wifi.ssid`` / ``wifi.password``.
* HTTP server: ``http_server.bind_host`` / ``bind_port`` /
  ``max_connections`` / ``request_timeout_ms`` / ``max_request_body_bytes``
  plus the optional TLS pair ``http_server.tls.cert_path`` /
  ``http_server.tls.key_path`` — all optional with library defaults
  (``0.0.0.0:8080``, plain TCP).

When ``runtime_config.msgpack`` isn't present (raw single-file deploy),
edit the ``WIFI_SSID`` / ``WIFI_PASSWORD`` constants below.  The server
falls back to ``0.0.0.0:8080``.

Try it
======

Deploy the example, watch its serial output for the IP it prints,
then from your laptop::

    curl http://<board-ip>:8080/
    curl http://<board-ip>:8080/api/uptime
    curl -X POST -H 'Content-Type: application/json' \\
         -d '{"hello": "board"}' http://<board-ip>:8080/api/echo

Example output (board side)::

    WIFI_OK ip=10.0.0.42
    Server listening on http://10.0.0.42:8080/
    [+] GET /
    [+] GET /api/uptime
    [+] POST /api/echo  body={"hello": "board"}
"""

#: Cross-runtime — wifi-up via :mod:`helpers` dispatches per
#: ``sys.implementation.name`` (CP / MP) and the HTTP server is
#: pure-Python.  The marker tells :func:`scripts.verify_examples`
#: + ``deploy-example`` to allow this file on either runtime.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_http_server import HttpServer, build_response
from helpers import runtime_config, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying

config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

server = HttpServer.from_config(config, radio=radio)

start_ticks = ticks_ms()


@server.route("/")
def index(_request):
    print("[+] GET /")
    body = (
        "<html><body><h1>chumicro http_server demo</h1>"
        "<p>Try <code>GET /api/uptime</code> and "
        "<code>POST /api/echo</code>.</p></body></html>"
    )
    return build_response(200, html=body)


@server.route("/api/uptime")
def uptime(_request):
    print("[+] GET /api/uptime")
    # ticks_ms wraps every ~6.2 days; ticks_diff handles the
    # signed wraparound math correctly.
    uptime_ms = ticks_diff(ticks_ms(), start_ticks)
    return build_response(200, json={"uptime_ms": uptime_ms})


@server.route("/api/echo", methods=["POST"])
def echo(request):
    payload = request.json()
    print(f"[+] POST /api/echo  body={payload!r}")
    return build_response(200, json={"echoed": payload})


bound_host = config.get("http_server.bind_host", "0.0.0.0")
bound_port = config.get("http_server.bind_port", 8080)
print(f"Server listening on http://{ip}:{bound_port}/  (bound {bound_host}:{bound_port})")

while True:
    if server.check(ticks_ms()):
        server.handle(ticks_ms())
    time.sleep(0.02)
