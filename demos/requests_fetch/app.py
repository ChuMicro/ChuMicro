"""Fetch a web page from a board every five seconds, without the board ever stopping.

This is the file that runs on the board.  It waits for wifi, fetches a
page from your laptop, prints what came back, waits five seconds, and
fetches it again, forever.  A heartbeat prints once a second through all
of it, so you can watch that fetching a page never freezes the program.

What the board prints::

    WIFI_OK ip=10.0.0.42
      GET http://10.0.0.5:54321/hello
    FETCHED status=200 bytes=49
    DEMO_COMPLETE
      {"message": "hello from the requests_fetch demo"}
      ...still ticking
      ...still ticking
      ...still ticking
      ...still ticking
      GET http://10.0.0.5:54321/hello
    FETCHED status=200 bytes=49
      {"message": "hello from the requests_fetch demo"}
      ...still ticking

The UPPERCASE lines are for the script on your laptop, which reads them
to follow how far the board got.  They are ordinary ``print`` calls in a
``NAME key=value`` shape, and a value may not contain a space or an
``=``.  That is why the URL and the page go on their own indented
lines: a URL with a ``?a=b`` query string would break the split.

When the laptop script finishes, its web server goes away, and each
fetch after that prints ``FETCH_FAILED`` instead.  The board keeps
trying every five seconds.

Two things worth trying:

* Swap ``config["requests.fetch.url"]`` near the bottom for a page of
  your own, such as ``"http://example.com/"``, and watch ``bytes=``
  change.
* Change ``FETCH_EVERY_MS`` and watch the heartbeats between fetches
  follow it.
"""

from chumicro_config import load_runtime_config
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_add, ticks_ms
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState

FETCH_EVERY_MS = 5_000


def fetch_forever(wifi, link_up, url):
    """Fetch the page every five seconds, forever.

    Each ``yield from`` is a place this pauses and the rest of the board
    runs.  It picks up on that same line when what it waited for is ready.
    """
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")
    factory = connector_factory(radio=wifi.adapter.radio)

    fetched = 0
    while True:
        print(f"  GET {url}")
        try:
            response = yield from get(factory, url)
            fetched += 1
            print(f"FETCHED status={response.status_code} "
                  f"bytes={len(response.body)}")
            if fetched == 1:
                print("DEMO_COMPLETE")
            print(f"  {response.text[:60]}")
        except Exception as error:
            print(f"FETCH_FAILED error={type(error).__name__}")
        yield from sleep_until(ticks_add(ticks_ms(), FETCH_EVERY_MS))


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
runner.add_generator(fetch_forever(wifi, link_up, config["requests.fetch.url"]))

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
