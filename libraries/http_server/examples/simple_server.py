"""Serve a web page from your board.

The board joins your wifi, prints its address, and answers web requests
for as long as it has power.  Open that address in a browser on the
same network and the board sends back a page saying how many requests
it has answered and how much memory it has free.  Every 30 seconds it
prints the same numbers to the serial console, which shows the main
loop stays free for your own code while the server waits for visitors.

Before you run it:

1. Install ``chumicro_http_server`` on the board, and copy
   ``helpers.py`` from this folder onto the board beside this file.
2. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.
3. Save this file to the board as ``code.py`` (CircuitPython) or
   ``main.py`` (MicroPython), and open the serial console.

From a ChuMicro workspace, ``chumicro-workspace deploy-example
http_server simple_server`` does all three steps and takes the wifi
details from ``secrets.toml``.

Then use the address the board printed.  Open
``http://<board-ip>:8080/`` in a browser, or from a terminal::

    curl http://<board-ip>:8080/status
    curl -d '{"hello": "board"}' http://<board-ip>:8080/echo

What you will see on the serial console::

    Joining wifi...
    Serving at http://10.0.0.42:8080/
    GET /
    GET /status
    POST /echo
      received {'hello': 'board'}
    Requests answered: 3, free memory: 151232 bytes.  Serving at http://10.0.0.42:8080/

Something to try: send ``/echo`` a body that is not JSON.  The route
raises an error, the server answers ``500`` with the error message,
and the board carries on serving.
"""

# Runs on CircuitPython and MicroPython; the deploy tools read this line.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import gc
import time

from chumicro_http_server import HttpServer, build_response
from helpers import runtime_config, ticks_add, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
REPORT_EVERY_MS = 30_000

# Join wifi.  wifi_up() waits until the board has an address.  When a
# deploy put wifi settings on the board, those win over the two above.
print("Joining wifi...")
config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)

# Make the server.  It listens on port 8080 unless the deployed settings
# name another.  On CircuitPython it opens its sockets through the radio.
server = HttpServer.from_config(config, radio=radio)
port = config.get("http_server.bind_port", 8080)
address = f"http://{ip}:{port}/"
requests_answered = 0


def log_request(request):
    """Print each request as it arrives and add it to the count."""
    global requests_answered
    requests_answered += 1
    print(request.method, request.path)


# Each route is a function the server calls when a request for its path
# arrives.  It gets the request and returns the response to send back.
@server.route("/")
def home(request):
    log_request(request)
    page = (
        "<h1>Hello from your board</h1>"
        f"<p>Requests answered: {requests_answered}<br>"
        f"Free memory: {gc.mem_free()} bytes</p>"
        '<p>The same numbers as JSON: <a href="/status">/status</a></p>'
    )
    return build_response(200, html=page)


@server.route("/status")
def status(request):
    log_request(request)
    return build_response(
        200, json={"requests_answered": requests_answered, "free_bytes": gc.mem_free()},
    )


@server.route("/echo", methods=["POST"])
def echo(request):
    log_request(request)
    data = request.json()
    print("  received", data)
    return build_response(200, json={"echoed": data})


# The first handle() opens the listening socket, so by the time the
# address prints, the board is already answering on it.
server.handle(ticks_ms())
print(f"Serving at {address}")

next_report_ms = ticks_add(ticks_ms(), REPORT_EVERY_MS)

while True:
    now_ms = ticks_ms()

    # Give the server its turn.  check() asks whether it has work, and a
    # server always does, since a visitor can arrive at any moment.
    # handle() accepts a waiting visitor, moves every open request one
    # step along, and returns within a few milliseconds.
    if server.check(now_ms):
        server.handle(now_ms)

    # The rest of your program goes here.  This part prints a status line
    # every 30 seconds.  ticks_diff() and ticks_add() do the arithmetic,
    # because the millisecond counter wraps back to zero about every six days.
    if ticks_diff(now_ms, next_report_ms) >= 0:
        print(
            f"Requests answered: {requests_answered}, "
            f"free memory: {gc.mem_free()} bytes.  Serving at {address}",
        )
        next_report_ms = ticks_add(now_ms, REPORT_EVERY_MS)

    time.sleep(0.01)  # a short rest so the loop does not spin flat out
