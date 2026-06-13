"""mqtt client: socket blocking mode, connect, disconnect, QoS 0/1
publish, subscribe."""

import select

from chumicro_mqtt import (
    MQTTClient,
    MQTTConnectError,
    ProtocolState,
    UnsupportedQoSError,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_puback_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
    drive,
    new_client,
)
from chumicro_runner import Runner
from chumicro_runner.testing import FakePoller
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness.assertions import raises
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
            connector_factory=factory,
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

    def test_connect_without_disconnected_state_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()  # sets state to CONNECTING
        with raises(Exception):  # noqa: B017
            client.connect()


class TestMultiTickConnect:
    """Connector-driven non-blocking connect.

    ``connect()`` returns immediately after arming the connector;
    DNS / TCP / TLS happen across subsequent ``handle()`` ticks so the
    runner is never blocked waiting on the network."""

    def test_connect_returns_immediately_in_awaiting_transport(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()
        # No network I/O on the caller's thread: state is AWAITING_TRANSPORT,
        # the CONNECT packet has not yet been queued, sock is untouched.
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert bytes(sock.sent) == b""

    def test_ticks_drive_through_dns_tcp_and_connect(self) -> None:
        """Tick 1 advances dns_ok; tick 2 advances tcp_ok, promotes the
        socket, drains CONNECT and (because CONNACK is pre-queued in
        the FakeSocket) reads it the same tick.  On a real wire the
        CONNACK arrives ticks later and the state lingers in CONNECTING
        between."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()

        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        assert bytes(sock.sent) == b""

        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.CONNECTED
        assert sock.sent[0] == 0x10  # CONNECT control byte landed on the wire

    def test_connector_failure_during_dns_lands_failed(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["fail:dns lookup failed"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.FAILED
        assert "connector failed" in str(client.last_error)
        assert "dns lookup failed" in str(client.last_error)

    def test_connector_failure_during_tcp_lands_failed(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "fail:connection refused"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="multitick",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())  # dns_ok
        client.handle(ticks.ticks_ms())  # fail
        assert client.state == ProtocolState.FAILED
        assert "connection refused" in str(client.last_error)

    def test_tls_handshake_yields_between_rounds(self) -> None:
        """TLS connector scripts a ``tls_pending`` round-trip; the client
        stays in AWAITING_TRANSPORT until ``tls_ok`` lands.  Demonstrates
        the runner doesn't see a multi-tick handshake as a single
        blocking call."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok", "tls_pending", "tls_ok"],
                socket=sock,
                tls=True,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="tls-multitick",
            ticks=ticks,
        )
        client.connect()
        # dns_ok
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # tcp_ok → awaiting_tls (does not enter ready because tls=True)
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # tls_pending → still awaiting_tls
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.AWAITING_TRANSPORT
        # tls_ok → ready → promote → CONNECT drained → CONNACK read → CONNECTED
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.CONNECTED

    def test_disconnect_during_awaiting_transport_cancels_connector(self) -> None:
        """A user-driven ``disconnect()`` mid-handshake cancels the
        in-flight connector and lands in DISCONNECTED — no DISCONNECT
        packet, the MQTT layer never came up."""
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_pending", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="cancel-test",
            ticks=ticks,
        )
        client.connect()
        client.handle(ticks.ticks_ms())  # dns_ok
        assert client.state == ProtocolState.AWAITING_TRANSPORT

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED
        # Connector dropped, no half-open socket retained.
        assert client._connector is None  # noqa: SLF001

    def test_connector_io_surface_forwarded_in_awaiting_transport(self) -> None:
        """``Runner.wait`` reads io_socket / io_wants_* / next_deadline
        off the client — during AWAITING_TRANSPORT they forward to the
        connector so the runner parks on the right pollable."""
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_pending", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="io-surface",
            ticks=ticks,
        )
        client.connect()
        # connector starts in awaiting_dns; one tick advances to awaiting_tcp
        # where io_wants_write is True (TCP connect phase needs POLLOUT).
        client.handle(ticks.ticks_ms())
        assert client.io_socket is sock
        assert client.io_wants_write is True
        assert client.io_wants_read is False
        assert client.next_deadline(0) is None

    def test_next_deadline_clamps_to_now_while_awaiting_dns(self) -> None:
        """Before the connector builds a socket (awaiting_dns, io_socket
        None), next_deadline returns now_ms so Runner.wait ticks the
        connector forward instead of sleeping; once dns_ok produces a
        pollable, the connector's deadline (None here) flows through."""
        sock = FakeSocket()
        ticks = FakeTicks()

        def factory():
            return FakeSocketConnector(
                actions=["dns_ok", "tcp_ok"], socket=sock,
            )

        client = MQTTClient(
            connector_factory=factory,
            client_id="clamp-test",
            ticks=ticks,
        )
        client.connect()
        # Fresh connector is in awaiting_dns: no socket yet, nothing for
        # Runner.wait to park on, so the deadline collapses to now_ms.
        assert client.io_socket is None
        assert client.next_deadline(777) == 777
        # One tick drives dns_ok; the connector now exposes its socket
        # and the clamp lifts (the connector reports no deadline of its own).
        client.handle(ticks.ticks_ms())
        assert client.io_socket is sock
        assert client.next_deadline(777) is None


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
        client = new_client(sock, ticks, root_topic="devices")
        client.set_will("status", b"offline", retain=True)
        client.connect()
        drive(client, ticks, count=1)
        # Prefix scheme applied: devices/<client_id>/status.
        assert b"devices/test-client/status" in bytes(sock.sent)
        assert b"offline" in bytes(sock.sent)

    def test_set_will_none_topic_disables_will(self) -> None:
        """set_will(topic=None) clears the will entirely."""
        ticks = FakeTicks()
        sock = FakeSocket()
        client = new_client(sock, ticks, root_topic="devices")
        client.set_will("status", b"offline")
        client.set_will(None)
        # Internal state is back to no-will.
        assert client._will_topic is None

    def test_set_will_unprefixed_bypasses_root_topic(self) -> None:
        """set_will(prefixed=False) sends the topic verbatim."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks, root_topic="devices")
        client.set_will("$SYS/bridge/dead", b"x", prefixed=False)
        client.connect()
        drive(client, ticks, count=1)
        # Verbatim topic on the wire.
        assert b"$SYS/bridge/dead" in bytes(sock.sent)
        assert b"devices/" not in bytes(sock.sent)


class TestPublishQos0:
    def test_qos0_writes_packet_immediately(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        sock.sent = bytearray()  # MP bytearray lacks .clear()
        client.publish("temp", b"42", qos=0)
        drive(client, ticks, count=1)
        # First byte 0x30 = PUBLISH qos 0.
        assert sock.sent[0] == 0x30
        assert b"temp" in bytes(sock.sent)
        assert bytes(sock.sent).endswith(b"42")

    def test_qos0_callback_fires_after_send(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []

        def capture(topic: str, payload: bytes) -> None:
            captured.append((topic, payload))

        client.publish("temp", b"42", qos=0, on_publish=capture)
        drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]

    def test_qos0_fires_global_on_publish_without_per_call_callback(self) -> None:
        """Global ``client.on_publish`` fires for QoS 0 sends.

        Matches the QoS 1 behavior so a user who sets the global
        callback once (rather than passing ``on_publish=`` on every
        call) sees every send.
        """
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []
        client.on_publish = lambda topic, payload: captured.append((topic, payload))
        client.publish("temp", b"42", qos=0)
        drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]


class TestPublishQos1:
    def test_qos1_publish_then_puback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []

        def _capture(topic: str, payload: bytes) -> None:
            captured.append((topic, payload))

        client.publish("temp", b"42", qos=1, on_publish=_capture)

        # After tick 3: PUBLISH on the wire.
        drive(client, ticks, count=1)
        # The packet_id allocated should be the next free (1: the
        # SUBACK/PUBACK pool is shared but no subs queued yet).
        assert b"temp" in bytes(sock.sent)
        # Now broker sends PUBACK.
        sock.enqueue_recv(canned_puback_bytes(packet_id=1))
        drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]

    def test_concurrent_qos1_publishes_dispatch_independently(self) -> None:
        """Two QoS 1 publishes at once both get their callbacks on PUBACK."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        first_called: list[bool] = []
        second_called: list[bool] = []
        client.publish(
            "first",
            b"1",
            qos=1,
            on_publish=lambda topic, payload: first_called.append(True),
        )
        client.publish(
            "second",
            b"2",
            qos=1,
            on_publish=lambda topic, payload: second_called.append(True),
        )
        # One send per tick: two queued PUBLISHes need two ticks.
        drive(client, ticks, count=2)  # Send both.

        # Broker pubacks them out of order.
        sock.enqueue_recv(canned_puback_bytes(packet_id=2))
        sock.enqueue_recv(canned_puback_bytes(packet_id=1))
        # One recv per tick: two FakeSocket PUBACK chunks need two ticks.
        drive(client, ticks, count=2)

        assert first_called == [True]
        assert second_called == [True]

    def test_qos1_retries_on_ack_timeout(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        sock.sent = bytearray()  # MP bytearray lacks .clear()
        client.publish("temp", b"42", qos=1)
        drive(client, ticks, count=1)
        first_send_length = len(sock.sent)
        # Skip past the ack timeout.  No PUBACK arrives.
        ticks.advance(10_000)
        drive(client, ticks, count=1)
        # Retry packet should now be on the wire (DUP flag set).
        assert len(sock.sent) > first_send_length
        retry_byte = sock.sent[first_send_length]
        assert retry_byte & 0x08  # DUP bit set on the retry

    def test_qos1_publish_qos2_raises(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        with raises(UnsupportedQoSError):
            client.publish("topic", b"x", qos=2)


class TestSubscribe:
    def test_subscribe_then_suback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[list[int]] = []
        client.subscribe(
            "sensors/+",
            qos=1,
            on_subscribe=lambda topic, granted: captured.append(granted),
        )
        drive(client, ticks, count=1)
        sock.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
        drive(client, ticks, count=1)
        assert captured == [[1]]

    def test_unsubscribe_then_unsuback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)

        captured: list[bool] = []
        client.unsubscribe(
            "sensors/+",
            on_unsubscribe=lambda topic: captured.append(True),
        )
        drive(client, ticks, count=1)
        sock.enqueue_recv(canned_unsuback_bytes(packet_id=1))
        drive(client, ticks, count=1)
        assert captured == [True]


class TestRunnerReactorContract:
    """``io_socket`` / ``io_wants_read`` / ``io_wants_write`` /
    ``next_deadline`` let ``Runner.wait`` register the broker socket
    and idle the loop until readiness or the next deadline fires."""

    def test_io_socket_none_when_disconnected(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        # state defaults to DISCONNECTED
        assert client.io_socket is None

    def test_io_socket_returns_socket_when_connected(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # FakeSocket has no ``_sock``; the property returns it directly.
        # Production adapters expose ``_sock`` and the property unwraps.
        assert client.io_socket is sock

    def test_io_socket_none_when_failed(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        client.state = ProtocolState.FAILED

        assert client.io_socket is None

    def test_io_wants_read_only_while_live(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        assert client.io_wants_read is False  # DISCONNECTED

        client.connect()
        assert client.io_wants_read is True  # CONNECTING
        drive(client, ticks, count=2)
        assert client.io_wants_read is True  # CONNECTED

    def test_io_wants_write_tracks_tx_queue(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        # DISCONNECTED + empty tx -> no.
        assert client.io_wants_write is False

        # connect() queues a CONNECT packet but does not drain yet.
        client.connect()
        assert client.io_wants_write is True

        # Drain the CONNECT, receive CONNACK -> tx queue empty.
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=2)
        assert client.io_wants_write is False

    def test_next_deadline_none_when_disconnected(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks)
        assert client.next_deadline(ticks.ticks_ms()) is None

    def test_next_deadline_returns_pending_ack_when_connecting(self) -> None:
        """``connect()`` enqueues a PendingResponse for CONNACK with an
        ack-timeout deadline; that becomes the next deadline."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = new_client(sock, ticks, ack_timeout_seconds=2.0)
        start = ticks.ticks_ms()
        client.connect()
        deadline = client.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        # ack_timeout is 2000 ms from connect().
        assert ticks.ticks_diff(deadline, start) == 2000

    def test_next_deadline_picks_keepalive_when_connected(self) -> None:
        """Once CONNECTED with no in-flight ACKs, next_deadline is the
        keepalive (PINGREQ-send) timer."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = new_client(
            sock, ticks, keep_alive_seconds=60, ack_timeout_seconds=5.0,
        )
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        deadline = client.next_deadline(ticks.ticks_ms())
        assert deadline is not None
        # Ping interval is half the keepalive (30000 ms from CONNECTED tick).
        # drive() advanced through 2 ticks; allow for that.
        assert ticks.ticks_diff(deadline, ticks.ticks_ms()) > 0

    def test_runner_wait_registers_socket_for_mqtt_lifecycle(self) -> None:
        """End-to-end: connect via Runner + FakePoller, observe POLLIN
        registration after the CONNECT drains, then unregister on
        disconnect."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        client = new_client(sock, ticks)
        runner.add(client)
        client.connect()

        # First wait observes io_wants_write True (CONNECT queued), so
        # the poll set should request POLLIN|POLLOUT initially.
        runner.wait(ticks.ticks_ms())
        first_marks = poller.register_calls + poller.modify_calls
        assert any(
            eventmask & select.POLLOUT
            for _sock, eventmask in first_marks
        )

        # Drive ticks to drain CONNECT and receive CONNACK.
        for _ in range(5):
            now_ms = runner.tick()
            runner.wait(now_ms)
            ticks.advance(1)
        assert client.state == ProtocolState.CONNECTED
        assert client.io_wants_write is False  # tx queue drained

        # CONNECTED + empty tx queue: only POLLIN remains.
        last_event = (
            poller.modify_calls[-1] if poller.modify_calls else poller.register_calls[-1]
        )
        _last_sock, last_mask = last_event
        assert last_mask == select.POLLIN

        # disconnect() closes the socket and transitions to DISCONNECTED;
        # the next wait sees io_socket=None and unregisters.
        client.disconnect()
        runner.wait(ticks.ticks_ms())
        assert sock in poller.unregister_calls
