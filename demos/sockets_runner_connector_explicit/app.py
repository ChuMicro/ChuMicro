"""Echo a line off a server every five seconds, written as a service class.

This is the file that runs on the board.  It joins wifi, then every five
seconds opens a TCP connection to a small echo server running on your
laptop, sends one line, reads the same line back, and hangs up.  A
heartbeat prints once a second the whole time.

The work lives in ``EchoService``, an object the runner calls over and
over.  The runner asks ``check(now_ms)`` ("anything to do?") and then
``handle(now_ms)`` ("go ahead").  ``self.state`` is how the object
remembers where it got to between calls: ``connecting``, then
``sending``, then ``receiving``, then ``resting`` until the next round.
Every call does as much as it can without waiting and returns, so the
heartbeat, wifi, and anything else you register keep their turns.

What you will see::

    WIFI_OK ip=10.0.0.42
    CONNECTING host=10.0.0.5 port=54321
      ...still ticking
    CONNECTED
    SENT bytes=15
    ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
      echo 1: 'hello chumicro' came back
    DEMO_COMPLETE
      ...still ticking
      ...still ticking
      ...still ticking
      ...still ticking
    CONNECTING host=10.0.0.5 port=54321
      ...still ticking
    CONNECTED
    SENT bytes=15
    ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
      echo 2: 'hello chumicro' came back

It never stops.  When the script on your laptop finishes, it shuts the
echo server down, and from then on each round prints ``ECHO_FAILED`` and
tries again five seconds later.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
That is why the payload rides as hex rather than as text.

Try adding a second ``EchoService`` with a different ``PROBE_PAYLOAD``:
both run on the same loop without waiting on each other.
"""

import errno

from chumicro_config import load_runtime_config
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_sockets import connector
from chumicro_timing import ticks_add, ticks_diff
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro\n"
RECV_BUFFER_SIZE = 64
ECHO_EVERY_MS = 5000


class EchoService:
    """Connect, send ``PROBE_PAYLOAD``, read the reply, rest, and go again.

    Call ``start()`` once the wifi link is up.
    """

    def __init__(self, host, port, radio):
        self.host = host
        self.port = port
        self.radio = radio
        self.state = "idle"
        self.echoes = 0
        self.dial = None
        self.socket = None
        self.sent = 0
        self.received = bytearray()
        self.buffer = bytearray(RECV_BUFFER_SIZE)
        self.next_round_ms = 0

    def start(self):
        """Begin the first round, unless one is already under way."""
        if self.state == "idle":
            self._begin_round()

    def check(self, now_ms):
        """Return ``True`` when ``handle`` has something to do this turn."""
        if self.state == "resting":
            return ticks_diff(now_ms, self.next_round_ms) >= 0
        return self.state != "idle"

    def handle(self, now_ms):
        """Take the next step for whichever state the round is in."""
        if self.state == "resting":
            self._begin_round()
        elif self.state == "connecting":
            self._connect_step(now_ms)
        elif self.state == "sending":
            self._send_step(now_ms)
        elif self.state == "receiving":
            self._receive_step(now_ms)

    def _begin_round(self):
        print(f"CONNECTING host={self.host} port={self.port}")
        self.dial = connector(self.host, self.port, radio=self.radio)
        self.state = "connecting"

    def _connect_step(self, now_ms):
        # The connector does DNS and the TCP handshake, one step per call.
        self.dial.tick(now_ms)
        if self.dial.state == "ready":
            print("CONNECTED")
            self.socket = self.dial.socket
            # Non-blocking, so send() and recv_into() raise EAGAIN instead
            # of holding the whole board while they wait for the network.
            self.socket.setblocking(False)
            self.sent = 0
            self.received = bytearray()
            self.state = "sending"
        elif self.dial.state == "failed":
            self._fail(self.dial.last_error, now_ms)

    def _send_step(self, now_ms):
        # send() may take only part of the payload, so keep count and carry on
        # from there.  EAGAIN means the socket is full: return, and the runner
        # calls back once it can take more.
        while self.sent < len(PROBE_PAYLOAD):
            try:
                count = self.socket.send(PROBE_PAYLOAD[self.sent:])
            except OSError as error:
                if error.args[0] != errno.EAGAIN:
                    self._fail(error, now_ms)
                return
            if count == 0:
                self._fail(OSError("echo server hung up"), now_ms)
                return
            self.sent += count
        print(f"SENT bytes={len(PROBE_PAYLOAD)}")
        self.state = "receiving"

    def _receive_step(self, now_ms):
        # EAGAIN means nothing has arrived yet: return, and the runner calls
        # back once bytes are waiting.
        try:
            count = self.socket.recv_into(self.buffer, RECV_BUFFER_SIZE)
        except OSError as error:
            if error.args[0] != errno.EAGAIN:
                self._fail(error, now_ms)
            return
        if count == 0:
            self._fail(OSError("echo server hung up before the newline"), now_ms)
            return
        self.received.extend(self.buffer[:count])
        if b"\n" not in self.received:
            return
        payload = bytes(self.received).rstrip(b"\n")
        print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
        self.echoes += 1
        print(f"  echo {self.echoes}: {payload.decode()!r} came back")
        if self.echoes == 1:
            print("DEMO_COMPLETE")
        self._rest(now_ms)

    def _fail(self, error, now_ms):
        print(f"ECHO_FAILED error={type(error).__name__}")
        print(f"  detail: {error!r}, trying again in five seconds")
        self._rest(now_ms)

    def _rest(self, now_ms):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        self.next_round_ms = ticks_add(now_ms, ECHO_EVERY_MS)
        self.state = "resting"

    # The runner reads the three hooks below before it parks the CPU, so it
    # wakes for the right socket event or for the next round's start time
    # instead of checking back over and over.

    @property
    def io_socket(self):
        """The socket to watch: the connector's while dialing, then this round's."""
        if self.state == "connecting":
            return self.dial.io_socket
        return self.socket

    def io_interest(self, now_ms):
        """Whether to wake when ``io_socket`` can be written to or read from."""
        if self.state == "connecting":
            return self.dial.io_interest(now_ms)
        if self.state == "sending":
            return IO_WRITE
        if self.state == "receiving":
            return IO_READ
        return 0

    def next_deadline(self, now_ms):
        """When to wake without a socket event: the connector's answer while dialing,
        the next round's start while resting, otherwise ``None``."""
        if self.state == "connecting":
            return self.dial.next_deadline(now_ms)
        if self.state == "resting":
            return self.next_round_ms
        return None


def heartbeat(now_ms):
    """Runs once a second, whatever else is going on."""
    print("  ...still ticking")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def on_wifi_state(_old, new):
    """Prints the address and starts the echoes once wifi is up."""
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        echo.start()


config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
echo = EchoService(
    config["sockets.echo.host"], int(config["sockets.echo.port"]),
    radio=wifi.adapter.radio,
)
wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add(echo)
runner.add_periodic(heartbeat, period_ms=1000)

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
