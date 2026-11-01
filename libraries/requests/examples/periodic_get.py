"""Fetch a web page every 30 seconds without ever stopping the loop.

The board joins your wifi, then asks ``http://example.com/`` for its
page every 30 seconds and prints the HTTP status code and how many
bytes came back.  A fetch that fails (wifi dropped, server down, no
answer within 10 seconds) prints the reason, and the next round tries
again.  The loop runs until you unplug the board.

If you have used ``adafruit_requests``, you know
``response = requests.get(url)``, which holds the whole board on that
line until the server answers.  ``client.get(url)`` returns at once
with a request object instead.  The ``while True`` loop at the bottom
calls ``client.handle(now_ms)`` on every pass.  Each call moves the
request one small step and returns, and ``request.done`` turns
``True`` when the answer is in.  Anything else you put in that loop
keeps running while the server works on its answer and while the page
downloads.

Before you run it:

1. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.  When you deploy with
   ``chumicro-workspace``, the ``ssid`` and ``password`` under
   ``[wifi]`` in your ``secrets.toml`` are used instead.
2. Deploy it::

       chumicro-workspace deploy-example requests periodic_get --device <id>

What you will see::

    WIFI_OK ip=10.0.0.42
    Fetching http://example.com/ every 30 s
    [1] status=200 bytes=577
    [2] status=200 bytes=577
    [3] status=200 bytes=577

A round that fails prints the reason in place of the status, for
example ``[4] failed: request to 'http://example.com/' timed out after
deadline``.

Try pointing ``URL`` at a JSON API and printing ``response.json()``.
"""

# Runs on CircuitPython and MicroPython boards.  helpers.wifi_up picks
# the right wifi calls for each.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_requests import HttpClient
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import Rate, ticks_ms
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
URL = "http://example.com/"
FETCH_EVERY_S = 30

# Join wifi.  wifi_up waits until the board has an IP address.
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# One client makes every request.  connector_factory tells it how to
# open a network connection through this board's wifi radio.
client = HttpClient(transport_factory=connector_factory(radio=radio))
print(f"Fetching {URL} every {FETCH_EVERY_S} s")

# Start the first fetch now.  get() returns straight away; the loop
# below carries the request through to the end.
fetch_number = 1
request = client.get(URL)
fetch_timer = Rate(FETCH_EVERY_S * 1000, ticks_ms())

while True:
    now_ms = ticks_ms()

    # check() is True while a request is in flight.  handle() moves it
    # one small step (connect, send, or read what has arrived) and
    # returns without waiting for the server.
    if client.check(now_ms):
        client.handle(now_ms)

    # The request finished: print what came back, or why it failed.
    if request is not None and request.done:
        if request.error is not None:
            print(f"[{fetch_number}] failed: {request.error}")
        else:
            response = request.response
            print(f"[{fetch_number}] status={response.status_code} bytes={len(response.body)}")
        request = None

    # Every FETCH_EVERY_S seconds, start the next fetch.
    if request is None and fetch_timer.due(now_ms):
        fetch_number += 1
        request = client.get(URL)

    # Anything else you add here, such as blinking an LED or reading a
    # button, runs on every pass, including while a page downloads.
