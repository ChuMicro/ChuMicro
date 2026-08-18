"""The same echo round trip as its sibling demo, written the long way.

This is the file that runs on the board.  It does exactly what
``sockets_runner_connector`` does: wait for wifi, connect to a small
echo server on your laptop, send one line, read the line that comes
back.  The difference is how it is written.

There, the whole conversation was one function with ``yield from`` at
each pause.  Here it is ``EchoService``, an object with a ``state``
string that walks ``idle`` to ``connecting`` to ``sending`` to
``receiving`` to ``done``.  The runner asks it ``check(now_ms)`` ("do
you want a turn?") and then ``handle(now_ms)`` ("here is your turn"),
and the service picks up wherever it left off.

Read the two side by side.  Nothing here is hidden from you in the
other one; it is the same steps, and ``yield from`` is what collapses
the bookkeeping.

What you will see::

    WIFI_OK ip=10.0.0.42
    CONNECTING host=10.0.0.5 port=54321
      ...still ticking
    CONNECTED
    SENT bytes=15
    ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
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
That is why the payload rides as hex rather than as text.
"""

import errno

from chumicro_config import load_runtime_config
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_sockets import connector
from chumicro_wifi import WifiConfig, WifiService, WifiState


class EchoService:
    """Connect to the echo server, send a line, read the reply, stop.

    ``self.state`` is where this object keeps its place: it walks
    ``idle`` → ``connecting`` → ``sending`` → ``receiving`` → ``done``.
    Each turn from the runner advances it as far as it can go without
    waiting, and then returns.  That is the rule the whole project runs
    on: do a little, give the turn back.

    Call ``start()`` once the wifi link is up.
    """

    PROBE_PAYLOAD = b"hello chumicro\n"
    RECV_BUFFER_SIZE = 64

    def __init__(self, host, port, radio):
        self._host = host
        self._port = port
        self._radio = radio
        self.connector = None
        self._socket = None
        self._buffer = bytearray(self.RECV_BUFFER_SIZE)
        self._received = bytearray()
        self._send_offset = 0
        self.state = "idle"

    @property
    def done(self):
        return self.state == "done"

    def start(self):
        """Build the ``SocketConnector`` and move into ``connecting``."""
        if self.connector is not None or self.state == "done":
            return
        print(f"CONNECTING host={self._host} port={self._port}")
        try:
            self.connector = connector(
                self._host, self._port, radio=self._radio,
            )
        except Exception as error:  # noqa: BLE001 - surface as marker, not traceback
            print(f"CONNECT_FAILED error={type(error).__name__}")
            print(f"  detail: {error!r}")
            self.state = "done"
            return
        self.state = "connecting"

    def check(self, _):
        # Tell Runner whether handle() should fire on the next wake.
        return self.state in ("connecting", "sending", "receiving")

    def handle(self, now_ms):
        if self.state == "connecting":
            self._handle_connecting(now_ms)
        elif self.state == "sending":
            self._handle_sending()
        elif self.state == "receiving":
            self._handle_receiving()

    def _handle_connecting(self, now_ms):
        # Drive the connector one phase (DNS → TCP → (TLS) → ready).
        self.connector.tick(now_ms)
        if self.connector.state == "ready":
            self._socket = self.connector.socket
            # Nonblocking so send() / recv() raise EAGAIN instead of stalling the runner.
            self._socket.setblocking(False)
            print("CONNECTED")
            self.state = "sending"
        elif self.connector.state == "failed":
            print(f"CONNECT_FAILED error={type(self.connector.last_error).__name__}")
            print(f"  detail: {self.connector.last_error!r}")
            self.state = "done"

    def _handle_sending(self):
        # A short send is normal; EAGAIN means resume next tick when writable.
        payload = memoryview(self.PROBE_PAYLOAD)
        while self._send_offset < len(payload):
            try:
                sent = self._socket.send(payload[self._send_offset:])
            except OSError as error:
                if error.args[0] == errno.EAGAIN:
                    return
                print(f"SEND_FAILED error={type(error).__name__}")
                print(f"  detail: {error!r}")
                self.state = "done"
                return
            if sent == 0:
                print("SEND_FAILED error=peer-closed")
                self.state = "done"
                return
            self._send_offset += sent
        print(f"SENT bytes={len(self.PROBE_PAYLOAD)}")
        self.state = "receiving"

    def _handle_receiving(self):
        try:
            number_of_bytes = self._socket.recv_into(
                self._buffer, self.RECV_BUFFER_SIZE,
            )
        except OSError as error:
            # EAGAIN means no bytes yet: wait for the next read-ready tick.
            if error.args[0] != errno.EAGAIN:
                print(f"RECV_FAILED error={type(error).__name__}")
                print(f"  detail: {error!r}")
                self.state = "done"
            return
        if number_of_bytes == 0:
            # recv_into() of 0 bytes signals the peer closed the connection.
            self.state = "done"
            return
        self._received.extend(self._buffer[:number_of_bytes])
        # The echo server terminates its reply with a newline.
        if b"\n" in self._received:
            payload = bytes(self._received).rstrip(b"\n")
            print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
            print("DEMO_COMPLETE")
            self._socket.close()
            self.state = "done"

    # Runner.wait() reads these to sleep on the right socket event:
    # delegate to the connector while connecting, then own the socket
    # (read while receiving, write while sending) after ready.

    @property
    def io_socket(self):
        if self.state == "connecting":
            return self.connector.io_socket
        if self._socket is None:
            return None
        return self._socket

    def io_interest(self, now_ms):  # noqa: ARG002 (runner contract)
        # One bitmask replaces the paired io_wants_read / io_wants_write
        # hooks: forward the connector's interest while connecting, then
        # want read while receiving and write while sending.
        if self.state == "connecting":
            return self.connector.io_interest(now_ms)
        if self.state == "receiving":
            return IO_READ
        if self.state == "sending":
            return IO_WRITE
        return 0


def heartbeat(now_ms):
    """Runs once a second, whatever else is going on."""
    print("  ...still ticking")


config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))
echo = EchoService(echo_host, echo_port, radio=wifi.adapter.radio)

def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


runner = Runner(on_handler_error=report_fault)


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        # Link is up.  Kick off the round trip.
        echo.start()


wifi.on_state_change(on_wifi_state)

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
