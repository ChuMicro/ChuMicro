"""Serve web pages from a board, for as long as the board has power.

This is the file that runs on the board.  It waits for wifi, starts a
small web server, and prints the address to point a browser at.  The
script on your laptop then sends three requests, one to each route
below.  Every five seconds the board prints a status line with the
address and how many requests it has answered, so you can see it is
still serving.

Each route is a plain function that takes a request and returns a
response.  The ``@server.route(...)`` line above it tells the server
which address that function answers.  The server takes its turn in the
loop at the bottom like everything else, which is why the status line
keeps printing while the board waits for requests.

What the board prints::

      starting up...
    WIFI_OK ip=10.0.0.42
    SERVER_READY ip=10.0.0.42 port=8080
    ROUTE_HIT route=/hello
    ROUTE_HIT route=/uptime uptime_ms=9873
    ROUTE_HIT route=/echo
    DEMO_COMPLETE
      serving http://10.0.0.42:8080/hello (3 requests so far)
      serving http://10.0.0.42:8080/hello (3 requests so far)

The UPPERCASE lines are for the script on your laptop, which reads them
to follow how far the board got and learns the board's address from
``SERVER_READY``.  They are ordinary ``print`` calls in a
``NAME key=value`` shape, and a value may not contain a space or an
``=``.  The indented lines are for you.

Try it: once ``SERVER_READY`` appears, open
``http://<the ip it printed>:8080/hello`` in your own browser and watch
the request count go up.  Then add a route of your own.
"""

from chumicro_config import load_runtime_config
from chumicro_http_server import HttpServer, build_response
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
server = HttpServer.from_config(config, radio=wifi.adapter.radio)
port = config.get("http_server.bind_port", 8080)

start_ms = ticks_ms()
requests_served = 0


def count_request():
    """Count one answered request.  The laptop script sends three."""
    global requests_served
    requests_served += 1
    if requests_served == 3:
        print("DEMO_COMPLETE")


@server.route("/hello")
def hello(_request):
    """Answer GET /hello with a small JSON body."""
    print("ROUTE_HIT route=/hello")
    count_request()
    return build_response(
        200, json={"message": "hello from chumicro_http_server"},
    )


@server.route("/uptime")
def uptime(_request):
    """Answer GET /uptime with how long this board has been running."""
    uptime_ms = ticks_diff(ticks_ms(), start_ms)
    print(f"ROUTE_HIT route=/uptime uptime_ms={uptime_ms}")
    count_request()
    return build_response(200, json={"uptime_ms": uptime_ms})


@server.route("/echo", methods=["POST"])
def echo(request):
    """Answer POST /echo by handing back the JSON it was sent."""
    print("ROUTE_HIT route=/echo")
    count_request()
    return build_response(200, json={"echoed": request.json()})


def start_server():
    """Wait for wifi, start the server, and print its address once it listens.

    The server cannot open its listening socket until wifi has given the
    board an address.  Each ``yield from`` pauses here for a quarter of a
    second while the rest of the board keeps running.
    """
    while not wifi.connected:
        yield from sleep_until(ticks_add(ticks_ms(), 250))
    runner.add(server)
    while not server.listening:
        yield from sleep_until(ticks_add(ticks_ms(), 250))
    print(f"WIFI_OK ip={wifi.ip}")
    print(f"SERVER_READY ip={wifi.ip} port={port}")


def report_status(now_ms):
    """Runs every five seconds, whatever else is going on."""
    if server.listening:
        print(f"  serving http://{wifi.ip}:{port}/hello "
              f"({requests_served} requests so far)")
    else:
        print("  starting up...")


runner = Runner()
runner.add(wifi)
runner.add_periodic(report_status, period_ms=5000)
runner.add_generator(start_server())

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends: this board goes on serving for as long as it has power.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
