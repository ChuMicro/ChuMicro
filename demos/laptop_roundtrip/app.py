"""laptop_roundtrip: one loop, one HTTP fetch, one blinking LED, no board.

Everything here runs in a single CPython process on 127.0.0.1.  A
``chumicro_http_server`` serves a route, a ``chumicro_requests`` generator
fetches it, and a simulated LED blinks on a ``chumicro_timing`` ``Rate``.
All three share one ``Runner`` and advance through ``runner.tick()`` /
``runner.wait()``, exactly as they would on a board.

The server hands its body back one line at a time on a timer, so the single
request stays in flight long enough to watch.  While it is in flight the loop
never stalls: the LED keeps its rhythm and ``runner.wait()`` idles the CPU
between events instead of spinning.  Run it with ``python app.py`` and read
the interleaving.
"""

import chumicro_sockets
from chumicro_http_server import HttpServer
from chumicro_http_server.streaming import SOURCE_EOF, build_streaming_response
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import Rate, ticks_add, ticks_diff, ticks_ms

# LED half-period: lit for BLINK_MS, dark for BLINK_MS.
BLINK_MS = 60
# The server streams this many lines, one every LINE_GAP_MS, so the whole
# fetch lasts about BODY_LINES * LINE_GAP_MS and spans several blinks.
BODY_LINES = 8
LINE_GAP_MS = 100


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


def build_server() -> tuple:
    """Open a loopback listener on an ephemeral port and wire one slow route."""
    # Port 0 asks the OS for a free port, so two runs never collide.
    listener = chumicro_sockets.listener("127.0.0.1", 0)
    host, port = listener.getsockname()
    server = HttpServer(transport_factory=lambda: listener)

    @server.route("/slow")
    def slow(_request):
        return build_streaming_response(
            200, source=DrippingBody(BODY_LINES, LINE_GAP_MS),
        )

    return server, host, port


def fetch(transport_factory: object, url: str):
    """Fetch *url* once as a generator; the runner drives it across ticks."""
    print(f"  fetch: GET {url}")
    response = yield from get(transport_factory, url)
    print(f"  fetch: {response.status_code}, {len(response.body)} bytes received")


def main() -> None:
    server, host, port = build_server()
    url = f"http://{host}:{port}/slow"

    runner = Runner()
    runner.add(server)                                    # accepts and serves each tick

    print(f"laptop_roundtrip: serving {url}")
    print("laptop_roundtrip: one fetch in flight, LED blinking on the same loop\n")

    # add_generator primes the fetch (prints its GET line) once the header is out.
    request = runner.add_generator(fetch(connector_factory(), url))

    blink = Rate(BLINK_MS, ticks_ms())
    lit = False
    blink_count = 0
    while not request.done:
        now = runner.tick()                               # server and fetch each take one step
        if blink.due(now):
            lit = not lit
            blink_count += 1
            print(f"  LED {'on ' if lit else 'off'}")
        runner.wait(now)                                  # idle the CPU until the next event

    print(f"\nlaptop_roundtrip: request finished; the LED blinked {blink_count} times "
          "without the loop ever stalling.")


if __name__ == "__main__":
    main()
