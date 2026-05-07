"""End-to-end tests for ``MQTTClient`` via FakeSocket + FakeTicks."""

from chumicro_mqtt import (
    MQTTBackpressureError,
    MQTTClient,
    MQTTConnectError,
    ProtocolState,
    UnsupportedQoSError,
    WhenOversized,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_pingresp_bytes,
    canned_puback_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
    canned_unsuback_bytes,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness.assertions import raises
from chumicro_timing.testing import FakeTicks


def _new_client(sock: FakeSocket, ticks: FakeTicks, **overrides) -> MQTTClient:
    """Build a client with FakeTicks injected."""
    kwargs = {
        "client_id": "test-client",
        "keep_alive_seconds": 60,
        "ack_timeout_seconds": 5.0,
        "publish_retry_max": 2,
        "ticks_ms_func": ticks.ticks_ms,
        "ticks_add_func": ticks.ticks_add,
        "ticks_diff_func": ticks.ticks_diff,
    }
    kwargs.update(overrides)
    return MQTTClient(sock, **kwargs)


def _drive(client: MQTTClient, ticks: FakeTicks, count: int = 1) -> None:
    """Run *count* tick iterations of the client."""
    for _ in range(count):
        now = ticks.ticks_ms()
        client.handle(now)


# ---------------------------------------------------------------------------
# Connect / Disconnect
# ---------------------------------------------------------------------------


class TestSocketBlockingMode:
    def test_init_forces_socket_non_blocking(self) -> None:
        """The MQTT client owns its socket's blocking mode.

        Phase 7 Layer-3 caught a Pi Pico W MP hang where the MP socket
        adapter constructed sockets in blocking mode (stdlib default)
        and the MQTT client's first tick called recv on a blocking
        socket — never returned, never saw CONNACK, ack-timeout fired
        after 5s, infinite reconnect loop.  Make MQTTClient enforce
        non-blocking on construction so the contract belongs to the
        client, not every consumer.
        """
        sock = FakeSocket()
        sock.setblocking(True)  # default-blocking before MQTTClient sees it
        ticks = FakeTicks()
        _new_client(sock, ticks)
        assert sock.blocking is False

    def test_self_heal_forces_replacement_socket_non_blocking(self) -> None:
        """The factory may hand back a blocking socket — heal still wins."""
        first_sock = FakeSocket()
        replacement = FakeSocket()
        replacement.setblocking(True)  # arrive blocking
        factory_calls: list[FakeSocket] = []

        def factory() -> FakeSocket:
            factory_calls.append(replacement)
            return replacement

        ticks = FakeTicks()
        client = MQTTClient(
            first_sock,
            socket_factory=factory,
            client_id="test-client",
            ack_timeout_seconds=5.0,
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        client.connect()  # marks user-wants-connected
        # Force the client into FAILED so handle() takes the self-heal path.
        client._state = ProtocolState.FAILED  # noqa: SLF001 — test wants the gate
        client.handle(ticks.ticks_ms())
        assert factory_calls == [replacement]
        assert replacement.blocking is False


class TestConnect:
    def test_handshake_transitions_to_connected(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)

        client.connect()
        assert client.state == ProtocolState.CONNECTING
        # First tick: send CONNECT.  Second: parse CONNACK.
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

    def test_connect_fires_on_connect_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)

        fired: list[bool] = []
        client.on_connect = lambda: fired.append(True)
        client.connect()
        _drive(client, ticks, count=2)
        assert fired == [True]

    def test_rejection_transitions_to_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=4))  # bad credentials
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.FAILED
        assert isinstance(client.last_error, MQTTConnectError)
        assert client.last_error.return_code == 4

    def test_connect_without_disconnected_state_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()  # sets state to CONNECTING
        with raises(Exception):  # noqa: B017
            client.connect()


class TestDisconnect:
    def test_sends_disconnect_packet_and_closes(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        client.disconnect()
        # DISCONNECT wire frame is the trailing two bytes.
        assert bytes(sock.sent[-2:]) == b"\xe0\x00"
        assert client.state == ProtocolState.DISCONNECTED
        assert sock.closed


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


class TestPublishQos0:
    def test_qos0_writes_packet_immediately(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        sock.sent = bytearray()  # MP bytearray lacks .clear()
        client.publish("temp", b"42", qos=0)
        _drive(client, ticks, count=1)
        # First byte 0x30 = PUBLISH qos 0.
        assert sock.sent[0] == 0x30
        assert b"temp" in bytes(sock.sent)
        assert bytes(sock.sent).endswith(b"42")

    def test_qos0_callback_fires_after_send(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []

        def capture(topic: str, payload: bytes) -> None:
            captured.append((topic, payload))

        client.publish("temp", b"42", qos=0, on_publish=capture)
        _drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]


class TestPublishQos1:
    def test_qos1_publish_then_puback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []

        def _capture(topic: str, payload: bytes) -> None:
            captured.append((topic, payload))

        client.publish("temp", b"42", qos=1, on_publish=_capture)

        # After tick 3: PUBLISH on the wire.
        _drive(client, ticks, count=1)
        # The packet_id allocated should be the next free (1 — the
        # SUBACK/PUBACK pool is shared but no subs queued yet).
        assert b"temp" in bytes(sock.sent)
        # Now broker sends PUBACK.
        sock.enqueue_recv(canned_puback_bytes(packet_id=1))
        _drive(client, ticks, count=1)
        assert captured == [("temp", b"42")]

    def test_concurrent_qos1_publishes_dispatch_independently(self) -> None:
        """Two QoS 1 publishes at once both get their callbacks on PUBACK."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

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
        _drive(client, ticks, count=1)  # Send both.

        # Broker pubacks them out of order — the original client got
        # confused here.
        sock.enqueue_recv(canned_puback_bytes(packet_id=2))
        sock.enqueue_recv(canned_puback_bytes(packet_id=1))
        _drive(client, ticks, count=1)

        assert first_called == [True]
        assert second_called == [True]

    def test_qos1_retries_on_ack_timeout(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        sock.sent = bytearray()  # MP bytearray lacks .clear()
        client.publish("temp", b"42", qos=1)
        _drive(client, ticks, count=1)
        first_send_length = len(sock.sent)
        # Skip past the ack timeout — no PUBACK arrives.
        ticks.advance(10_000)
        _drive(client, ticks, count=1)
        # Retry packet should now be on the wire (DUP flag set).
        assert len(sock.sent) > first_send_length
        retry_byte = sock.sent[first_send_length]
        assert retry_byte & 0x08  # DUP bit set on the retry

    def test_qos1_publish_qos2_raises(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        with raises(UnsupportedQoSError):
            client.publish("topic", b"x", qos=2)


# ---------------------------------------------------------------------------
# Subscribe / Unsubscribe
# ---------------------------------------------------------------------------


class TestSubscribe:
    def test_subscribe_then_suback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[list[int]] = []
        client.subscribe(
            "sensors/+",
            qos=1,
            on_subscribe=lambda topic, granted: captured.append(granted),
        )
        _drive(client, ticks, count=1)
        sock.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
        _drive(client, ticks, count=1)
        assert captured == [[1]]

    def test_unsubscribe_then_unsuback_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[bool] = []
        client.unsubscribe(
            "sensors/+",
            on_unsubscribe=lambda topic: captured.append(True),
        )
        _drive(client, ticks, count=1)
        sock.enqueue_recv(canned_unsuback_bytes(packet_id=1))
        _drive(client, ticks, count=1)
        assert captured == [True]


# ---------------------------------------------------------------------------
# Inbound publish dispatching
# ---------------------------------------------------------------------------


class TestInboundPublish:
    def test_on_message_fires(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []
        client.on_message = lambda topic, payload: captured.append((topic, payload))
        sock.enqueue_recv(canned_publish_bytes("temp", b"99", qos=0))
        _drive(client, ticks, count=1)
        assert captured == [("temp", b"99")]

    def test_qos1_publish_triggers_puback_send(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()  # MP bytearray lacks .clear()

        sock.enqueue_recv(canned_publish_bytes("temp", b"99", qos=1, packet_id=42))
        _drive(client, ticks, count=2)

        # PUBACK 42 should be on the wire.
        assert b"\x40\x02\x00\x2a" in bytes(sock.sent)

    def test_pattern_handlers_fire(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[str] = []
        client.add_pattern_handler(
            "sensors/+/temperature",
            lambda topic, payload: captured.append(topic),
        )
        sock.enqueue_recv(canned_publish_bytes("sensors/back-porch/temperature", b"21", qos=0))
        sock.enqueue_recv(canned_publish_bytes("other/topic", b"x", qos=0))
        _drive(client, ticks, count=1)
        assert captured == ["sensors/back-porch/temperature"]


# ---------------------------------------------------------------------------
# Keepalive
# ---------------------------------------------------------------------------


class TestKeepalive:
    def test_pingreq_sent_at_half_interval(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        _drive(client, ticks, count=2)
        sock.sent = bytearray()  # MP bytearray lacks .clear()

        # Just past the 15-second mark — half of keepalive.
        ticks.advance(15_500)
        _drive(client, ticks, count=1)
        assert b"\xc0\x00" in bytes(sock.sent)  # PINGREQ wire bytes

    def test_pingresp_clears_pending(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        _drive(client, ticks, count=2)
        ticks.advance(15_500)
        _drive(client, ticks, count=1)
        sock.enqueue_recv(canned_pingresp_bytes())
        _drive(client, ticks, count=1)
        # PINGRESP arriving means the pending entry got cleared and
        # a PINGRESP timeout doesn't trip.
        assert client.state == ProtocolState.CONNECTED


# ---------------------------------------------------------------------------
# Oversized message policy
# ---------------------------------------------------------------------------


class TestWhenOversized:
    def test_drop_with_event_fires_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_size=8192,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[tuple[str, int]] = []
        client.on_oversized = lambda topic, length: captured.append((topic, length))
        sock.enqueue_recv(canned_publish_bytes("log", b"x" * 200, qos=0))
        # Drive enough ticks for the decoder's degraded path to drain.
        _drive(client, ticks, count=10)
        assert len(captured) == 1
        assert captured[0][0] == "log"

    def test_disconnect_policy_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_size=8192,
            when_oversized=WhenOversized.DISCONNECT,
        )
        client.connect()
        _drive(client, ticks, count=2)

        sock.enqueue_recv(canned_publish_bytes("log", b"x" * 200, qos=0))
        _drive(client, ticks, count=10)
        assert client.state == ProtocolState.FAILED


# ---------------------------------------------------------------------------
# Operations require connected
# ---------------------------------------------------------------------------


class TestNotConnectedGuards:
    def test_publish_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        with raises(Exception):  # noqa: B017
            client.publish("x", b"y")

    def test_subscribe_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        with raises(Exception):  # noqa: B017
            client.subscribe("x")

    def test_unsubscribe_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        with raises(Exception):  # noqa: B017
            client.unsubscribe("x")


# ---------------------------------------------------------------------------
# Error-path coverage — keep these tight + targeted
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_handle_in_disconnected_returns_immediately(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        # No connect — state is DISCONNECTED.
        # handle() should be a no-op (no recv attempt, no send).
        assert sock.sent == bytearray()
        client.handle(ticks.ticks_ms())
        assert sock.sent == bytearray()

    def test_check_returns_false_when_disconnected(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        assert client.check(ticks.ticks_ms()) is False

    def test_oserror_during_send_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        # Inject OSError on next send.
        original_send = sock.send

        def _broken_send(_data: bytes) -> int:
            raise OSError(2, "broken pipe")

        sock.send = _broken_send  # type: ignore[assignment]
        client.publish("x", b"y", qos=0)
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        sock.send = original_send  # type: ignore[assignment]

    def test_pingresp_timeout_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, keep_alive_seconds=30)
        client.connect()
        _drive(client, ticks, count=2)
        # Skip past keepalive — PINGREQ goes out, no PINGRESP arrives.
        ticks.advance(15_500)
        _drive(client, ticks, count=1)  # Sends PINGREQ, registers pending.
        ticks.advance(10_000)  # Past ack_timeout (5 s).
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_qos1_exceeds_retry_limit_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, publish_retry_max=1)
        client.connect()
        _drive(client, ticks, count=2)
        client.publish("x", b"y", qos=1)
        _drive(client, ticks, count=1)
        # No PUBACK ever arrives.  Two ack-timeouts: first triggers
        # one retry; second exceeds publish_retry_max → FAILED.
        ticks.advance(10_000)
        _drive(client, ticks, count=1)
        ticks.advance(10_000)
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED


class TestDecoderEdgeCases:
    def test_oversized_disconnect_policy_raises_protocol_error(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_size=8192,
            when_oversized=WhenOversized.DISCONNECT,
        )
        client.connect()
        _drive(client, ticks, count=2)
        sock.enqueue_recv(canned_publish_bytes("topic", b"x" * 200, qos=0))
        _drive(client, ticks, count=10)
        assert client.state == ProtocolState.FAILED

    def test_oversized_drop_silent_does_not_fire_callback(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(
            sock, ticks,
            rx_buffer_size=64,
            max_message_size=8192,
            when_oversized=WhenOversized.DROP_SILENT,
        )
        client.connect()
        _drive(client, ticks, count=2)
        captured: list[object] = []
        client.on_oversized = lambda topic, length: captured.append((topic, length))
        sock.enqueue_recv(canned_publish_bytes("topic", b"x" * 200, qos=0))
        _drive(client, ticks, count=10)
        assert captured == []
        assert client.state == ProtocolState.CONNECTED  # silent drop, still connected


# ---------------------------------------------------------------------------
# Wifi-drop survivability: socket factory + self-heal
# ---------------------------------------------------------------------------


class TestSocketFactorySelfHeal:
    """The Phase 7 wifi-drop story.

    When ``MQTTClient`` is constructed with a ``socket_factory``, a tick
    in ``FAILED`` state rebuilds the socket via the factory and re-issues
    ``connect()`` automatically — the thing's run loop sees mqtt come
    back without writing any recovery code.
    """

    def test_neither_socket_nor_factory_raises(self) -> None:
        with raises(ValueError, match="socket or a socket_factory"):
            MQTTClient(client_id="x")

    def test_factory_only_constructor_builds_initial_socket(self) -> None:
        ticks = FakeTicks()
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        builds: list[FakeSocket] = []

        def factory() -> FakeSocket:
            builds.append(sock)
            return sock

        client = MQTTClient(
            socket_factory=factory,
            client_id="x",
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        # Factory was invoked once at __init__ to build the initial socket.
        assert len(builds) == 1
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Factory not called a second time — the socket is healthy.
        assert len(builds) == 1

    def test_failed_state_with_factory_self_heals_and_reconnects(self) -> None:
        """Factory is called on FAILED + handle(); a new socket comes up."""
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        sockets = iter([sock_one, sock_two])

        def factory() -> FakeSocket:
            return next(sockets)

        client = MQTTClient(
            socket_factory=factory,
            client_id="heal-test",
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # Force FAILED — simulate a wifi-drop that killed the socket.
        client._state = ProtocolState.FAILED  # noqa: SLF001 — test seam
        _drive(client, ticks, count=2)

        # Self-heal ran: factory built a new socket, connect re-issued,
        # CONNACK arrived, back to CONNECTED on a different socket.
        assert client.state == ProtocolState.CONNECTED
        # The send on sock_two contains a CONNECT (post-self-heal handshake).
        assert b"\x10" in bytes(sock_two.sent)  # CONNECT first byte = 0x10

    def test_failed_state_without_factory_stays_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)  # no socket_factory

        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        client._state = ProtocolState.FAILED  # noqa: SLF001 — test seam
        _drive(client, ticks, count=5)
        # No factory → no self-heal, stays FAILED.
        assert client.state == ProtocolState.FAILED

    def test_factory_raise_keeps_client_failed(self) -> None:
        """Wifi still down → factory raises → client stays FAILED, retries next tick."""
        ticks = FakeTicks()
        initial_sock = FakeSocket()
        initial_sock.enqueue_recv(canned_connack_bytes(return_code=0))
        recovery_sock = FakeSocket()
        recovery_sock.enqueue_recv(canned_connack_bytes(return_code=0))
        attempts: list[bool] = []

        def factory() -> FakeSocket:
            if not attempts:
                attempts.append(True)  # initial __init__ build
                return initial_sock
            if len(attempts) < 4:
                attempts.append(False)
                raise OSError("wifi still down")
            attempts.append(True)
            return recovery_sock

        client = MQTTClient(
            socket_factory=factory,
            client_id="retry-test",
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        client._state = ProtocolState.FAILED  # noqa: SLF001 — test seam
        # Factory raises on the next 3 attempts; client stays FAILED.
        _drive(client, ticks, count=3)
        assert client.state == ProtocolState.FAILED
        assert "wifi still down" in str(client.last_error)

        # 4th attempt: factory returns the recovery socket, self-heal succeeds.
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

    def test_explicit_disconnect_disables_self_heal(self) -> None:
        """User-driven disconnect() must not auto-reconnect via the factory."""
        ticks = FakeTicks()
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        builds: list[None] = []

        def factory() -> FakeSocket:
            builds.append(None)
            return sock

        client = MQTTClient(
            socket_factory=factory,
            client_id="disconnect-test",
            ticks_ms_func=ticks.ticks_ms,
            ticks_add_func=ticks.ticks_add,
            ticks_diff_func=ticks.ticks_diff,
        )
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        initial_build_count = len(builds)

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED

        # Force FAILED — even with the factory present, the user-driven
        # disconnect should keep self-heal off.
        client._state = ProtocolState.FAILED  # noqa: SLF001 — test seam
        _drive(client, ticks, count=5)
        assert client.state == ProtocolState.FAILED
        assert len(builds) == initial_build_count  # factory not called again


class _CountingSocket(FakeSocket):
    """FakeSocket that counts bytes received via recv_into.

    Used by the bounded-recv tests to assert per-tick read budget
    is honored without leaking the assertion into FakeSocket itself.
    """

    def __init__(self) -> None:
        super().__init__()
        self.bytes_received_total = 0
        self.bytes_received_per_call: list[int] = []

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        got = super().recv_into(buffer, nbytes)
        if got > 0:
            self.bytes_received_total += got
            self.bytes_received_per_call.append(got)
        return got


class TestBoundedRecvPerTick:
    """``_read_inbound`` honors ``recv_budget_per_tick``.

    Phase 7 follow-up: a 100 KB inbound PUBLISH would otherwise
    monopolize the tick while the kernel TCP buffer drains, and
    side tasks (LED blink, LCD update, control loop) would stutter.
    """

    def _connected_client(self, sock: _CountingSocket, ticks: FakeTicks, **kwargs):
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        client = _new_client(sock, ticks, **kwargs)
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Reset counters after the CONNACK consume so the budget tests
        # only measure inbound-publish reads.
        sock.bytes_received_total = 0
        sock.bytes_received_per_call.clear()
        return client

    def test_budget_caps_bytes_consumed_per_tick(self) -> None:
        """A single tick cannot consume more than ``recv_budget_per_tick``."""
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(sock, ticks, recv_budget_per_tick=512)

        # Queue a 4 KB payload in a single chunk; FakeSocket honors
        # recv_into's *nbytes* cap so we'll consume in pieces.
        big_publish = canned_publish_bytes("topic/a", b"x" * 4096, qos=0)
        sock.enqueue_recv(big_publish)

        client.handle(ticks.ticks_ms())
        assert sock.bytes_received_total <= 512

    def test_default_budget_is_1024_bytes(self) -> None:
        """Default budget keeps tick latency LED-friendly out of the box."""
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(sock, ticks)  # default budget

        # Stuff a multi-KB blob; assert the default 1024-byte cap holds.
        big_publish = canned_publish_bytes("topic/a", b"x" * 8192, qos=0)
        sock.enqueue_recv(big_publish)
        client.handle(ticks.ticks_ms())
        assert sock.bytes_received_total <= 1024

    def test_budget_eventually_drains_full_payload_across_ticks(self) -> None:
        """Multiple ticks accumulate; a big blob arrives complete eventually.

        Configures a 16 KB ``rx_buffer_size`` so an 8 KB PUBLISH
        stays on the steady-state path (the default 256 B buffer
        would route it through the oversized-message handler and
        ``on_message`` wouldn't fire).
        """
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(
            sock, ticks, recv_budget_per_tick=1024, rx_buffer_size=16384,
        )

        received_payloads: list[bytes] = []
        client.on_message = lambda topic, payload: received_payloads.append(payload)

        big_payload = b"y" * 8192
        sock.enqueue_recv(canned_publish_bytes("topic/big", big_payload, qos=0))

        # Drive until the payload arrives — ~9 ticks at 1024 B/tick
        # for 8192 + small header bytes total.
        for _ in range(20):
            _drive(client, ticks, count=1)
            if received_payloads:
                break
        assert received_payloads == [big_payload]

    def test_small_payload_drains_in_a_single_tick(self) -> None:
        """The budget never makes the *easy* case slower."""
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(sock, ticks, recv_budget_per_tick=1024)

        small = b"hello"
        sock.enqueue_recv(canned_publish_bytes("topic/small", small, qos=0))

        seen: list[bytes] = []
        client.on_message = lambda topic, payload: seen.append(payload)
        client.handle(ticks.ticks_ms())
        assert seen == [small]


class TestTxQueueBackpressure:
    """User-initiated publishes raise ``MQTTBackpressureError`` past the cap."""

    def test_default_cap_is_100_packets(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)  # default cap
        assert client._max_tx_queue_size == 100  # noqa: SLF001 — pin the default

    def test_publish_raises_when_cap_exceeded(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, max_tx_queue_size=3)
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Queue is empty post-CONNECT.  Three publishes fill it; the
        # fourth should raise.  Don't drive between publishes so the
        # queue actually accumulates.
        client.publish("topic/a", b"one", qos=0)
        client.publish("topic/a", b"two", qos=0)
        client.publish("topic/a", b"three", qos=0)
        with raises(MQTTBackpressureError, match="tx queue full"):
            client.publish("topic/a", b"four", qos=0)

    def test_qos1_publish_rolls_back_packet_id_on_backpressure(self) -> None:
        """If the user-tx enqueue trips the cap, the in-flight allocation
        must be rolled back so the packet_id pool isn't leaked."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, max_tx_queue_size=1)
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # First QoS 1 publish fills the cap.
        client.publish("topic/a", b"one", qos=1)
        in_flight_after_first = list(client._in_flight)  # noqa: SLF001
        assert len(in_flight_after_first) == 1

        # Second publish overflows; expect the packet_id allocation to
        # be discarded along with the raise.
        with raises(MQTTBackpressureError):
            client.publish("topic/a", b"two", qos=1)
        in_flight_after_failed = list(client._in_flight)  # noqa: SLF001
        assert len(in_flight_after_failed) == 1  # rolled back, not leaked
        assert in_flight_after_failed[0].packet_id == in_flight_after_first[0].packet_id

    def test_protocol_internal_traffic_bypasses_cap(self) -> None:
        """PUBACK responses on inbound QoS 1 PUBLISHes are protocol
        bookkeeping; they must enqueue even if the user TX queue is
        full, otherwise QoS 1 contract breaks."""
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks, max_tx_queue_size=1)
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # Fill the user cap.
        client.publish("topic/a", b"user-pub", qos=0)

        # Now an inbound QoS 1 PUBLISH from the broker — handler must
        # enqueue the PUBACK even though the user-cap is full.
        sock.enqueue_recv(canned_publish_bytes(
            "topic/in", b"hi from broker", qos=1, packet_id=42,
        ))
        # No exception — internal enqueue bypasses the cap.
        client.handle(ticks.ticks_ms())


class TestFromConfig:
    """``MQTTClient.from_config`` reads the manifest's optional keys
    with sensible defaults; non-config args (socket, socket_factory,
    radio) come through kwargs."""

    @staticmethod
    def _injected_factory(sock: FakeSocket):
        """Return a socket_factory that hands back *sock*."""
        return lambda: sock

    def test_reads_all_keys_from_config(self) -> None:
        """A complete config dict populates every documented manifest key."""
        sock = FakeSocket()
        config = {
            "mqtt.broker.host": "10.0.0.5",  # consumed by default factory only
            "mqtt.broker.port": 8883,         # consumed by default factory only
            "mqtt.client_id": "thing-007",
            "mqtt.keep_alive_seconds": 120,
            "mqtt.username": "bob",
            "mqtt.password": "pw",
        }
        client = MQTTClient.from_config(
            config, socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "thing-007"  # noqa: SLF001
        assert client._keep_alive_seconds == 120  # noqa: SLF001
        assert client._username == "bob"  # noqa: SLF001
        assert client._password == "pw"  # noqa: SLF001

    def test_defaults_apply_when_keys_absent(self) -> None:
        """Empty config dict → every manifest key falls back to its default."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {}, socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "chumicro-mqtt"  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001
        assert client._username is None  # noqa: SLF001
        assert client._password is None  # noqa: SLF001

    def test_partial_config_mixes_overrides_with_defaults(self) -> None:
        """Caller-set keys win; absent keys take defaults."""
        sock = FakeSocket()
        client = MQTTClient.from_config(
            {"mqtt.client_id": "halfway"},
            socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "halfway"  # noqa: SLF001
        assert client._keep_alive_seconds == 60  # noqa: SLF001 — default
        assert client._username is None  # noqa: SLF001 — default

    def test_explicit_socket_bypasses_factory(self) -> None:
        """Passing a pre-built socket skips the auto-built factory entirely
        — caller owns the connection."""
        sock = FakeSocket()
        client = MQTTClient.from_config({}, socket=sock)
        assert client._socket is sock  # noqa: SLF001

    def test_runtime_config_wrapper_works_too(self) -> None:
        """Real ``RuntimeConfig`` instance — same flat-key reads as a
        plain dict.  Confirms compatibility with ``chumicro_config.config``
        on a real device."""
        from chumicro_config import RuntimeConfig  # noqa: PLC0415

        sock = FakeSocket()
        config = RuntimeConfig({
            "mqtt.client_id": "rc-test",
            "mqtt.keep_alive_seconds": 45,
        })
        client = MQTTClient.from_config(
            config, socket_factory=self._injected_factory(sock),
        )
        assert client._client_id == "rc-test"  # noqa: SLF001
        assert client._keep_alive_seconds == 45  # noqa: SLF001

    def test_default_factory_uses_config_broker_host_port(self) -> None:
        """When neither *socket* nor *socket_factory* is passed,
        ``from_config`` builds a factory that reads
        ``mqtt.broker.host`` / ``mqtt.broker.port`` from the config.
        Validates the factory closure without needing a real socket
        by monkey-patching ``chumicro_sockets.tcp_client_socket``."""
        captured: dict = {}

        def fake_tcp_client_socket(host, port, *, radio=None):
            captured["host"] = host
            captured["port"] = port
            captured["radio"] = radio
            return FakeSocket()

        import chumicro_sockets  # noqa: PLC0415

        original = chumicro_sockets.tcp_client_socket
        chumicro_sockets.tcp_client_socket = fake_tcp_client_socket
        try:
            MQTTClient.from_config(
                {"mqtt.broker.host": "10.0.0.42", "mqtt.broker.port": 8883},
                radio="fake-radio",
            )
        finally:
            chumicro_sockets.tcp_client_socket = original

        assert captured == {"host": "10.0.0.42", "port": 8883, "radio": "fake-radio"}

    def test_default_factory_requires_broker_host(self) -> None:
        """No broker host in config → ``from_config`` refuses to
        construct.  The library does not silently dial a third-party
        broker on the user's behalf."""
        from chumicro_config import MissingConfigKey  # noqa: PLC0415

        with raises(MissingConfigKey):
            MQTTClient.from_config({})

    def test_default_factory_requires_broker_port(self) -> None:
        """Host present but port missing still raises — both keys are
        required by the auto-built socket factory."""
        from chumicro_config import MissingConfigKey  # noqa: PLC0415

        with raises(MissingConfigKey):
            MQTTClient.from_config({"mqtt.broker.host": "10.0.0.42"})
