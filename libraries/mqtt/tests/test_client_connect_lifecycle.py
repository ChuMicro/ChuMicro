"""mqtt client: socket blocking mode, connect, disconnect, set-will."""


from chumicro_mqtt import (
    MQTTClient,
    MQTTConnectError,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


class TestSocketBlockingMode:
    def test_init_forces_socket_non_blocking(self) -> None:
        """``MQTTClient.__init__`` flips its socket to non-blocking.

        The tick-based recv path requires EAGAIN-on-no-data.  A socket
        in blocking mode would hang the first ``handle()`` call waiting
        for CONNACK so the client would never converge.  The MP socket
        adapter on Pi Pico W constructs blocking sockets by default
        (matching stdlib), so the contract belongs to the client, not
        every consumer.
        """
        sock = FakeSocket()
        sock.setblocking(True)  # default-blocking before MQTTClient sees it
        ticks = FakeTicks()
        new_client(sock, ticks)
        assert sock.blocking is False

    def test_self_heal_forces_replacement_socket_non_blocking(self) -> None:
        """The factory may hand back a blocking socket.  Heal still wins."""
        first_sock = FakeSocket()
        replacement = FakeSocket()
        replacement.setblocking(True)  # arrive blocking
        factory_calls: list[FakeSocket] = []

        def factory():
            factory_calls.append(replacement)
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=replacement,
            )

        ticks = FakeTicks()
        client = MQTTClient(
            first_sock,
            transport_factory=factory,
            client_id="test-client",
            ack_timeout_seconds=5.0,
            ticks=ticks,
        )
        client.connect()  # marks user-wants-connected
        # Force the client into FAILED so handle() takes the self-heal path.
        client.state = ProtocolState.FAILED
        # Two ticks: self-heal builds connector + advances dns_ok; next
        # tick advances tcp_ok → ready → promotes socket + forces non-blocking.
        client.handle(ticks.ticks_ms())
        client.handle(ticks.ticks_ms())
        assert factory_calls == [replacement]
        assert replacement.blocking is False


class TestConnect:
    def test_handshake_transitions_to_connected(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)

        client.connect()
        assert client.state == ProtocolState.CONNECTING
        # First tick: send CONNECT.  Second: parse CONNACK.
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

    def test_connect_fires_on_connect_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)

        fired: list[bool] = []
        client.on_connect = lambda: fired.append(True)
        client.connect()
        drive(client, ticks, count=2)
        assert fired == [True]

    def test_rejection_transitions_to_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=4))  # bad credentials
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.FAILED
        assert isinstance(client.last_error, MQTTConnectError)
        assert client.last_error.return_code == 4

    def test_connect_while_connecting_is_idempotent_noop(self) -> None:
        # connect() is an intent, not a state-transition guard: called
        # again while the connect is already in flight (CONNECTING) it is
        # an idempotent no-op — no raise, no second connector, no state
        # disturbance.  The "be connected" intent is already satisfied.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()  # sets state to CONNECTING
        assert client.state == ProtocolState.CONNECTING
        sent_after_first = bytes(sock.sent)
        client.connect()  # no-op
        assert client.state == ProtocolState.CONNECTING
        # No second CONNECT packet queued.
        assert bytes(sock.sent) == sent_after_first


class TestDisconnect:
    def test_sends_disconnect_packet_and_closes(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        client.disconnect()
        # DISCONNECT wire frame is the trailing two bytes.
        assert bytes(sock.sent[-2:]) == b"\xe0\x00"
        assert client.state == ProtocolState.DISCONNECTED
        assert sock.closed

    def test_second_disconnect_does_not_refire_callback(self) -> None:
        """A second ``disconnect()`` against an already-DISCONNECTED
        client is a no-op: no extra on_disconnect fire, no second
        DISCONNECT packet on the wire, no double socket close."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        fired: list[bool] = []
        client.on_disconnect = lambda: fired.append(True)
        client.connect()
        drive(client, ticks, count=2)

        client.disconnect()
        assert fired == [True]
        bytes_after_first = bytes(sock.sent)

        # Second disconnect: should be a no-op.
        client.disconnect()
        assert fired == [True]
        assert bytes(sock.sent) == bytes_after_first

    def test_disconnect_from_failed_skips_disconnect_packet(self) -> None:
        """Disconnecting from FAILED still cleans up but doesn't try to
        send a DISCONNECT packet (the socket is likely dead)."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        sock.sent = bytearray()  # Reset after CONNECT bytes.
        client.state = ProtocolState.FAILED

        client.disconnect()
        # No DISCONNECT packet sent on a presumed-dead socket.
        assert bytes(sock.sent) == b""
        assert client.state == ProtocolState.DISCONNECTED


class TestSetWill:
    def test_set_will_updates_topic_for_next_connect(self) -> None:
        """set_will modifies the will the next CONNECT packet carries."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.set_will("devices/status", b"offline", retain=True)
        client.connect()
        drive(client, ticks, count=1)
        # The will topic goes on the wire exactly as written.
        assert b"devices/status" in bytes(sock.sent)
        assert b"offline" in bytes(sock.sent)

    def test_set_will_none_topic_disables_will(self) -> None:
        """set_will(topic=None) clears the will entirely."""
        ticks = FakeTicks()
        sock = FakeSocket()
        client = new_client(sock, ticks)
        client.set_will("status", b"offline")
        client.set_will(None)
        # Internal state is back to no-will.
        assert client._will_topic is None
