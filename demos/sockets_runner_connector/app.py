"""Board-side of the sockets_runner_connector demo — sockets via runner.

Shows how to use ``chumicro_sockets`` under ``chumicro_runner``.  An
``EchoService`` class wraps the TCP round trip (connect, send, read
echo) and gets added to the runner with ``runner.add(echo)`` at
startup.  Like ``MQTTClient.connect()``, it stays dormant until the
wifi-state callback fires ``echo.start()`` once the link is up.

The lifecycle is an explicit state field — ``idle`` → ``connecting``
→ ``sending`` → ``receiving`` → ``done``.  ``handle`` dispatches to
one method per state so each phase has a single concern.

The service exposes ``io_socket`` / ``io_wants_read`` /
``io_wants_write`` so the runner sleeps on socket-ready events
instead of polling.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``HEARTBEAT``, ``DEMO_COMPLETE``) drive the host
driver via stdout markers.
"""

import errno

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import tcp_client_connector
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_PROBE_PAYLOAD = b"hello chumicro\n"
_RECV_BUFFER_SIZE = 64
_HEARTBEAT_INTERVAL_MS = 500


class EchoService:
    """Connect to the echo server, send a probe, read the echo, exit.

    Two-phase init like ``MQTTClient``: pass the radio at construction
    (the runtime's radio object exists from boot), then call ``start()``
    when the link is actually up.  ``start()`` is also where the
    ``SocketConnector`` gets built, so ``handle`` never needs a
    "first tick" branch.

    ``self.state`` walks ``idle`` → ``connecting`` → ``sending`` →
    ``receiving`` → ``done``.  Each transition is an explicit
    ``self.state = ...`` line.
    """

    def __init__(self, host, port, radio):
        self._host = host
        self._port = port
        self._radio = radio
        self._connector = None
        self._buffer = bytearray(_RECV_BUFFER_SIZE)
        self._received = bytearray()
        self.state = "idle"

    @property
    def done(self):
        return self.state == "done"

    def start(self):
        """Build the connector and begin the round trip."""
        print(f"CONNECTING host={self._host} port={self._port}")
        self._connector = tcp_client_connector(
            self._host, self._port, radio=self._radio,
        )
        self.state = "connecting"

    def check(self, now_ms):  # noqa: ARG002 (runner contract)
        return self.state not in ("idle", "done")

    def handle(self, now_ms):
        if self.state == "connecting":
            self._handle_connecting(now_ms)
        elif self.state == "sending":
            self._handle_sending()
        elif self.state == "receiving":
            self._handle_receiving()

    def _handle_connecting(self, now_ms):
        self._connector.tick(now_ms)
        if self._connector.state == "ready":
            self._connector.socket.setblocking(False)
            print("CONNECTED")
            self.state = "sending"
        elif self._connector.state == "failed":
            print(f"CONNECT_FAILED error={self._connector.last_error!r}")
            self.state = "done"

    def _handle_sending(self):
        self._connector.socket.send(_PROBE_PAYLOAD)
        print(f"SENT bytes={len(_PROBE_PAYLOAD)}")
        self.state = "receiving"

    def _handle_receiving(self):
        sock = self._connector.socket
        try:
            number_of_bytes = sock.recv_into(self._buffer, _RECV_BUFFER_SIZE)
        except OSError as error:
            if error.args[0] != errno.EAGAIN:
                print(f"RECV_FAILED error={error!r}")
                self.state = "done"
            return
        if number_of_bytes == 0:
            self.state = "done"
            return
        self._received.extend(self._buffer[:number_of_bytes])
        if b"\n" in self._received:
            payload = bytes(self._received).rstrip(b"\n")
            print(f"ECHO_RECEIVED bytes={len(payload)} payload={payload!r}")
            sock.close()
            self.state = "done"
            print("DEMO_COMPLETE")

    @property
    def io_socket(self):
        return self._connector.io_socket if self._connector is not None else None

    @property
    def io_wants_read(self):
        if self.state == "receiving":
            return True
        return self._connector.io_wants_read if self._connector is not None else False

    @property
    def io_wants_write(self):
        if self.state == "sending":
            return True
        return self._connector.io_wants_write if self._connector is not None else False


config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))
echo = EchoService(echo_host, echo_port, radio=wifi.adapter.radio)


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        echo.start()


wifi.on_state_change(on_wifi_state)

start_ms = ticks_ms()


def heartbeat(now_ms):
    print(f"HEARTBEAT uptime_ms={ticks_diff(now_ms, start_ms)}")


runner = Runner()
runner.add(wifi)
runner.add(echo)
runner.add_periodic(heartbeat, period_ms=_HEARTBEAT_INTERVAL_MS)

while not echo.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
