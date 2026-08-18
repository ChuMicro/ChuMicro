"""Fetch one web page from a board, without the rest of the board stopping.

This is the file that runs on the board.  It waits for wifi, makes one
HTTP GET, prints what came back, and ticks a heartbeat through the whole
thing so you can watch that fetching a page never froze the program.

What you will see::

    WIFI_OK ip=10.0.0.42
    FETCHING
      GET http://10.0.0.5:54321/hello
      ...still ticking
      ...still ticking
    FETCHED status=200 bytes=49
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
That is why the URL above is printed on its own indented line rather
than as ``url=...``; a URL with a ``?a=b`` query string would break the
split.

Two things worth trying:

* Point ``requests.fetch.url`` at a page of your own and watch ``bytes=``
  change.
* Unplug your router before you start.  The heartbeat keeps printing
  while the board retries the connection, which is the thing this whole
  project exists for.
"""

from chumicro_config import load_runtime_config
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState


def fetch_run(wifi, link_up, url):
    """The fetch, top to bottom.

    Each ``yield from`` is a place this pauses and the rest of the board
    runs.  It picks up on that same line when what it waited for is ready.
    """
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")

    factory = connector_factory(radio=wifi.adapter.radio)
    print("FETCHING")
    print(f"  GET {url}")

    response = yield from get(factory, url)
    print(f"FETCHED status={response.status_code} bytes={len(response.body)}")
    print("DEMO_COMPLETE")


def heartbeat(now_ms):
    """Runs once a second, whatever else is going on."""
    print("  ...still ticking")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def signal_link_up(_old, new):
    """Tells the fetch it can start."""
    if new == WifiState.CONNECTED:
        link_up.set(new)


config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
link_up = Signal()
wifi.on_state_change(signal_link_up)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add_periodic(heartbeat, period_ms=1000)
runner.add_generator(fetch_run(wifi, link_up, config["requests.fetch.url"]))

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
