"""Board-side echo demo: sockets via runner.

``EchoService`` runs one TCP round trip (connect, send a probe,
read the echo, exit) under ``chumicro_runner``.  It stays dormant
until the wifi link is up, then ``start()`` builds the
``SocketConnector`` and the service drives it through DNS / TCP /
TLS inside its own ``handle``.  Once the connector reaches
``ready``, the service takes over the socket for send / recv.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver.
"""

import errno

from chumicro_config import load_runtime_config
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_sockets import connector
from chumicro_test_harness.markers import marker
from chumicro_wifi import WifiConfig, WifiService, WifiState


class EchoService:
    """Connect to the echo server, send a probe, read the echo, exit.

    ``self.state`` walks ``idle`` → ``connecting`` → ``sending`` →
    ``receiving`` → ``done``.  Pass the radio at construction; call
    ``start()`` once the wifi link is up.  ``handle`` drives the
    ``SocketConnector`` through ``connecting``; this service owns
    ``self._socket`` for send and recv after ``ready``.
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
        marker("CONNECTING", host=self._host, port=self._port)
        try:
            self.connector = connector(
                self._host, self._port, radio=self._radio,
            )
        except Exception as error:  # noqa: BLE001 - surface as marker, not traceback
            marker("CONNECT_FAILED", error=type(error).__name__)
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
            marker("CONNECTED")
            self.state = "sending"
        elif self.connector.state == "failed":
            marker("CONNECT_FAILED", error=type(self.connector.last_error).__name__)
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
                marker("SEND_FAILED", error=type(error).__name__)
                print(f"  detail: {error!r}")
                self.state = "done"
                return
            if sent == 0:
                marker("SEND_FAILED", error="peer-closed")
                self.state = "done"
                return
            self._send_offset += sent
        marker("SENT", bytes=len(self.PROBE_PAYLOAD))
        self.state = "receiving"

    def _handle_receiving(self):
        try:
            number_of_bytes = self._socket.recv_into(
                self._buffer, self.RECV_BUFFER_SIZE,
            )
        except OSError as error:
            # EAGAIN means no bytes yet: wait for the next read-ready tick.
            if error.args[0] != errno.EAGAIN:
                marker("RECV_FAILED", error=type(error).__name__)
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
            marker("ECHO_RECEIVED", bytes=len(payload), payload_hex=payload)
            self._socket.close()
            self.state = "done"
            marker("DEMO_COMPLETE")

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


config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))
echo = EchoService(echo_host, echo_port, radio=wifi.adapter.radio)

runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        marker("WIFI_OK", ip=wifi.ip)
        # Link is up.  Kick off the round trip.
        echo.start()


wifi.on_state_change(on_wifi_state)

runner.add(wifi)
runner.add(echo)

while not echo.done:
    # tick() runs every ready task; wait() sleeps until the next io event or deadline.
    now_ms = runner.tick()
    runner.wait(now_ms)
