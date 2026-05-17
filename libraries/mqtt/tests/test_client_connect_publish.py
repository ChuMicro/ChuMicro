"""mqtt client: socket blocking mode, connect, disconnect, QoS 0/1
publish, subscribe. Sibling slices: other test_client_*.py."""

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
        "ticks": ticks,
    }
    kwargs.update(overrides)
    return MQTTClient(sock, **kwargs)

def _drive(client: MQTTClient, ticks: FakeTicks, count: int = 1) -> None:
    """Run *count* tick iterations of the client."""
    for _ in range(count):
        now = ticks.ticks_ms()
        client.handle(now)


class TestSocketBlockingMode:
    def test_init_forces_socket_non_blocking(self) -> None:
        """The MQTT client owns its socket's blocking mode.

        On a Pi Pico W MP the socket adapter constructs sockets in
        blocking mode (stdlib default); the client's first tick then
        called recv on a blocking socket — never returned, never saw
        CONNACK, ack-timeout fired after 5s, infinite reconnect loop.
        ``MQTTClient`` enforces non-blocking on construction so the
        contract belongs to the client, not every consumer.
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
            ticks=ticks,
        )
        client.connect()  # marks user-wants-connected
        # Force the client into FAILED so handle() takes the self-heal path.
        client.state = ProtocolState.FAILED
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

    def test_qos0_fires_global_on_publish_without_per_call_callback(self) -> None:
        """`client.on_publish = ...` must fire for QoS 0 too.

        Pre-fix: the per-call ``on_publish=`` kwarg was the only path
        that enqueued the post-send callback marker, so a user who set
        the global ``client.on_publish`` (the way the QoS 1 path
        already worked) saw QoS 1 events but not QoS 0 events.
        """
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)

        captured: list[tuple[str, bytes]] = []
        client.on_publish = lambda topic, payload: captured.append((topic, payload))
        client.publish("temp", b"42", qos=0)
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
