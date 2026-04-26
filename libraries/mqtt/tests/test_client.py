"""End-to-end tests for ``MQTTClient`` via FakeSocket + FakeTicks."""

import pytest
from chumicro_mqtt import (
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
        with pytest.raises(Exception):  # noqa: B017
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

        sock.sent.clear()
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

        sock.sent.clear()
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
        with pytest.raises(UnsupportedQoSError):
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
        sock.sent.clear()

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
        sock.sent.clear()

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
        with pytest.raises(Exception):  # noqa: B017
            client.publish("x", b"y")

    def test_subscribe_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        with pytest.raises(Exception):  # noqa: B017
            client.subscribe("x")

    def test_unsubscribe_before_connect_raises(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        with pytest.raises(Exception):  # noqa: B017
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
        with pytest.raises(ValueError, match="socket or a socket_factory"):
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
