"""laptop_roundtrip: an HTTP server, a client, and a blinking LED on one loop, no board.

Everything here runs in one Python process on your laptop.  A
``chumicro_http_server`` serves a ``/slow`` route, a ``chumicro_requests``
generator fetches it over and over, and a pretend LED flips on and off
every quarter second.  All three share one ``Runner`` and take turns
through ``runner.tick()`` and ``runner.wait()``, exactly as they would on
a board.

The server sends its reply one line at a time on a timer, so each fetch
stays in flight for about two seconds.  Watch the LED lines while it
does: they keep their rhythm, because nothing in the loop waits on the
fetch.  Between steps, ``runner.wait()`` idles the CPU instead of
spinning.

Run it with ``python app.py`` from this directory.  What you will see::

    laptop_roundtrip: serving http://127.0.0.1:51579/slow, press Ctrl-C to stop
      fetch 1: GET http://127.0.0.1:51579/slow
      LED on
      LED off
      LED on
      LED off
      LED on
      LED off
      LED on
      fetch 1: 200, 224 bytes, while the LED flipped 7 times
      LED off
      LED on
      LED off
      LED on
      fetch 2: GET http://127.0.0.1:51579/slow

It keeps going until you press Ctrl-C.  Try setting ``LINE_GAP_MS`` to
1000: each fetch takes four times as long, and the LED still flips every
quarter second.
"""

import chumicro_sockets
from chumicro_http_server import HttpServer
from chumicro_http_server.streaming import SOURCE_EOF, build_streaming_response
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

# The LED flips every BLINK_MS.
BLINK_MS = 250
# The server sends BODY_LINES lines, one every LINE_GAP_MS, so each fetch
# lasts about BODY_LINES * LINE_GAP_MS and spans several flips.
BODY_LINES = 8
LINE_GAP_MS = 250
# The rest between one fetch finishing and the next one starting.
PAUSE_MS = 1000


class DrippingBody:
    """Streaming source that emits one line every ``gap_ms``, then signals EOF.

    Returning ``0`` means "no bytes ready this tick", which is how a
    streaming source yields the loop without closing the connection: the
    server retries it on the next tick.  Here that models a slow upstream
    link so a bare loopback fetch does not finish in microseconds.
    """

    def __init__(self, line_count: int, gap_ms: int) -> None:
        self._line_count = line_count
        self._gap_ms = gap_ms
        self._sent = 0
        self._next_ms = ticks_ms()

    def __call__(self, buffer: object) -> int:
        if self._sent >= self._line_count:
            return SOURCE_EOF
        if ticks_diff(ticks_ms(), self._next_ms) < 0:
            return 0
        line = f"line {self._sent + 1} of {self._line_count} from the server\n".encode()
        buffer[:len(line)] = line
        self._sent += 1
        self._next_ms = ticks_add(ticks_ms(), self._gap_ms)
        return len(line)


def blink(now_ms):
    """Runs every ``BLINK_MS``: flips the pretend LED and counts the flip."""
    global lit, flips
    lit = not lit
    flips += 1
    print(f"  LED {'on' if lit else 'off'}")


def fetch_forever(transport_factory, url):
    """Fetch *url*, rest ``PAUSE_MS``, and go again, forever.

    Each ``yield from`` is a place this pauses so the server and the LED
    get their turns; it picks up on that same line when there is more to do.
    """
    global flips
    fetches = 0
    while True:
        fetches += 1
        flips = 0
        print(f"  fetch {fetches}: GET {url}")
        try:
            response = yield from get(transport_factory, url)
            print(f"  fetch {fetches}: {response.status_code}, {len(response.body)} bytes, "
                  f"while the LED flipped {flips} times")
        except Exception as error:
            print(f"  fetch {fetches} failed: {error!r}")
        yield from sleep_until(ticks_add(ticks_ms(), PAUSE_MS))


# Port 0 asks the operating system for a free port, so two runs never collide.
listener = chumicro_sockets.listener("127.0.0.1", 0)
host, port = listener.getsockname()
url = f"http://{host}:{port}/slow"
server = HttpServer(transport_factory=lambda: listener)


@server.route("/slow")
def slow(_request):
    """Answers with ``BODY_LINES`` lines, one every ``LINE_GAP_MS``."""
    return build_streaming_response(200, source=DrippingBody(BODY_LINES, LINE_GAP_MS))


lit = False
flips = 0
print(f"laptop_roundtrip: serving {url}, press Ctrl-C to stop")

runner = Runner()
runner.add(server)                                # accepts and answers requests
runner.add_periodic(blink, period_ms=BLINK_MS)    # flips the LED on a timer
runner.add_generator(fetch_forever(connector_factory(), url))

# The main loop.  tick() gives the server, the LED, and the fetch one
# small step each, and wait() then idles the CPU until the next socket
# event or timer deadline.  It never ends; Ctrl-C is the off switch.
try:
    while True:
        now_ms = runner.tick()
        runner.wait(now_ms)
except KeyboardInterrupt:
    print("\nlaptop_roundtrip: stopped.")
