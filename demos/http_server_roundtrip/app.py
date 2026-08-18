"""Serve web pages from a board, and answer three requests from a laptop.

This is the file that runs on the board.  It waits for wifi, starts a
small HTTP server, prints the address it is listening on, and answers
requests until the demo is done.

Three routes are registered with the ``@server.route(...)`` decorator.
Each one is a plain function that takes a request and returns a
response, and the server calls it when a matching request arrives.

Serving is not a mode the board goes into.  The server is a service like
any other, it gets one turn per pass through the loop, and anything else
you register keeps getting its turns too.

What you will see::

    WIFI_OK ip=10.0.0.42
    SERVER_READY ip=10.0.0.42 port=8080
      ...still ticking
    ROUTE_HIT route=/hello
    ROUTE_HIT route=/uptime uptime_ms=1873
    ROUTE_HIT route=/echo
    DEMO_COMPLETE
      ...still ticking
      ...still ticking

Nothing stops after that.  The loop goes on turning, the way a board
program does, and the script on your laptop closes the connection once
it has seen what it came for.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
That is how the laptop learns the board's address, off the
``SERVER_READY`` line.

Worth trying: while it is still running, open
``http://<the ip it printed>:8080/hello`` in your own browser.
"""

from chumicro_config import load_runtime_config
from chumicro_http_server import HttpServer, build_response
from chumicro_runner import Runner
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService

DEMO_ROUTES = ("/hello", "/uptime", "/echo")

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
server = HttpServer.from_config(config, radio=wifi.adapter.radio)
bind_port = config.get("http_server.bind_port", 8080)

hit_routes = []
start_ticks_ms = ticks_ms()


@server.route("/hello")
def hello(_request):
    """Answer GET /hello with a small JSON body."""
    hit_routes.append("/hello")
    print("ROUTE_HIT route=/hello")
    announce_if_done()
    return build_response(
        200, json={"message": "hello from chumicro_http_server"},
    )


@server.route("/uptime")
def uptime(_request):
    """Answer GET /uptime with how long this board has been running."""
    hit_routes.append("/uptime")
    uptime_ms = ticks_diff(ticks_ms(), start_ticks_ms)
    print(f"ROUTE_HIT route=/uptime uptime_ms={uptime_ms}")
    announce_if_done()
    return build_response(200, json={"uptime_ms": uptime_ms})


@server.route("/echo", methods=["POST"])
def echo(request):
    """Answer POST /echo by handing back the JSON it was sent."""
    hit_routes.append("/echo")
    print("ROUTE_HIT route=/echo")
    announce_if_done()
    return build_response(200, json={"echoed": request.json()})


def heartbeat(now_ms):
    """Runs once a second, whatever else is going on."""
    print("  ...still ticking")


def announce_if_done():
    """Say so once all three routes have been hit."""
    if len(hit_routes) == len(DEMO_ROUTES):
        print("DEMO_COMPLETE")


runner = Runner()
runner.add(wifi)
runner.add_periodic(heartbeat, period_ms=1000)

server_registered = False
announced = False


def bring_up_server(now_ms):
    """Start the server once wifi is up, then announce the address.

    The server cannot open its listening socket before the radio has an
    address, so this waits for the link instead of starting at boot.
    It is registered with the runner like everything else, so "waiting"
    costs nothing: it is just a function that returns early.
    """
    global server_registered, announced

    if not server_registered:
        if not wifi.connected:
            return
        runner.add(server)
        server_registered = True
        return

    if not announced and server.io_socket is not None:
        print(f"WIFI_OK ip={wifi.ip}")
        print(f"SERVER_READY ip={wifi.ip} port={bind_port}")
        announced = True


runner.add(handler=bring_up_server)

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does: this board goes on
# serving for as long as it has power.  Your own project's loop looks
# exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
