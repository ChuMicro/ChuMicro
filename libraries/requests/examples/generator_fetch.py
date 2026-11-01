"""Fetch a web page every 30 seconds, written as one top-to-bottom function.

The board joins your wifi, then fetches ``http://example.com/`` every
30 seconds and prints the HTTP status code and how many bytes came
back.  A fetch that fails prints the reason, and the next round tries
again.  The loop runs until you unplug the board.

This does the same job as ``periodic_get.py`` in a different style.
The fetch inside ``fetch_forever`` reads like ``adafruit_requests``
code::

    response = yield from get(connector, URL)

``yield from`` is the difference.  ``requests.get(url)`` holds the
whole board until the server answers; ``yield from get(...)`` pauses
only ``fetch_forever`` and hands the board back to the ``while True``
loop at the bottom of the file.  When the response is in, the runner
picks ``fetch_forever`` up again on that same line.
``yield from sleep_until(...)`` pauses it the same way for the 30
seconds between fetches.

``fetch_forever`` has its own ``while True``: it is the job, repeated
forever.  The loop at the bottom runs the board.  ``runner.tick()``
gives ``fetch_forever`` a turn whenever the thing it is waiting for is
ready, and ``runner.wait()`` rests the CPU until then.

Before you run it:

1. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.  When you deploy with
   ``chumicro-workspace``, the ``ssid`` and ``password`` under
   ``[wifi]`` in your ``secrets.toml`` are used instead.
2. Deploy it::

       chumicro-workspace deploy-example requests generator_fetch --device <id>

What you will see::

    WIFI_OK ip=10.0.0.42
    Fetching http://example.com/ every 30 s
    [1] status=200 bytes=577
    [2] status=200 bytes=577
    [3] status=200 bytes=577

A round that fails prints the reason in place of the status, for
example ``[4] failed: request to 'http://example.com/' timed out after
deadline``.
"""

# Runs on CircuitPython and MicroPython boards.  helpers.wifi_up picks
# the right wifi calls for each.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_requests import HttpError
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_add, ticks_ms
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
URL = "http://example.com/"
FETCH_EVERY_S = 30

# Join wifi.  wifi_up waits until the board has an IP address.
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# connector tells get() how to open a network connection through this
# board's wifi radio.
connector = connector_factory(radio=radio)
print(f"Fetching {URL} every {FETCH_EVERY_S} s")


def fetch_forever():
    fetch_number = 0
    while True:
        fetch_number += 1
        try:
            # Pauses here until the whole response has arrived.
            response = yield from get(connector, URL)
            print(f"[{fetch_number}] status={response.status_code} bytes={len(response.body)}")
        except (HttpError, OSError) as error:
            print(f"[{fetch_number}] failed: {error}")

        # Pauses here for FETCH_EVERY_S seconds.
        yield from sleep_until(ticks_add(ticks_ms(), FETCH_EVERY_S * 1000))


runner = Runner()
runner.add_generator(fetch_forever())

while True:
    now_ms = runner.tick()  # fetch_forever takes its turn if what it waits for is ready
    runner.wait(now_ms)  # the CPU rests until data arrives or the 30 s are up
