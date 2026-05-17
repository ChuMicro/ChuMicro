"""mqtt client: unexpected acks, socket-factory self-heal, bounded
recv per tick, tx-queue backpressure (uses _CountingSocket)."""

from chumicro_mqtt import (
    MQTTBackpressureError,
    MQTTClient,
    ProtocolState,
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
        "ticks": ticks,
    }
    kwargs.update(overrides)
    return MQTTClient(sock, **kwargs)

def _drive(client: MQTTClient, ticks: FakeTicks, count: int = 1) -> None:
    """Run *count* tick iterations of the client."""
    for _ in range(count):
        now = ticks.ticks_ms()
        client.handle(now)

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


class TestUnexpectedAcks:
    def test_unexpected_puback_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        # PUBACK with no matching in-flight entry.
        sock.enqueue_recv(canned_puback_bytes(packet_id=999))
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_unexpected_suback_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        sock.enqueue_recv(canned_suback_bytes(packet_id=999, granted_qos=0))
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_unexpected_unsuback_marks_failed(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        sock.enqueue_recv(canned_unsuback_bytes(packet_id=999))
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED

    def test_unexpected_pingresp_silently_tolerated(self) -> None:
        """PINGRESP with no pending tracker keeps the connection alive.

        Reason: PINGREQ timeout fires (clearing the tracker), the
        broker's PINGRESP arrives a tick later — re-faulting through a
        healthy connection would be a false positive.
        """
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        client.connect()
        _drive(client, ticks, count=2)
        # PINGRESP with no pending tracker.
        sock.enqueue_recv(canned_pingresp_bytes())
        _drive(client, ticks, count=1)
        assert client.state == ProtocolState.CONNECTED


class TestSocketFactorySelfHeal:
    """The wifi-drop survivability story.

    When ``MQTTClient`` is constructed with a ``socket_factory``, a tick
    in ``FAILED`` state rebuilds the socket via the factory and re-issues
    ``connect()`` automatically — the thing's run loop sees mqtt come
    back without writing any recovery code.
    """

    def test_neither_socket_nor_factory_raises(self) -> None:
        with raises(ValueError, match="socket or a socket_factory"):
            MQTTClient(client_id="x")

    def test_factory_only_constructor_defers_socket_build_to_connect(self) -> None:
        """Factory is NOT called at construction — only when connect() runs.

        Construction is side-effect free: ``__init__`` must not open
        sockets, so network errors land in ``state == FAILED`` /
        ``last_error`` instead of propagating out of the constructor
        where the runner contract can't see them.
        """
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
            ticks=ticks,
        )
        # No socket built at construction.
        assert len(builds) == 0
        assert client.state == ProtocolState.DISCONNECTED

        client.connect()
        # Factory invoked exactly once during connect().
        assert len(builds) == 1
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Factory not called a second time — the socket is healthy.
        assert len(builds) == 1

    def test_factory_failure_in_connect_marks_failed(self) -> None:
        """OSError from the factory at connect() time lands as FAILED + last_error."""
        ticks = FakeTicks()

        def factory():
            raise OSError(103, "ECONNABORTED")

        client = MQTTClient(
            socket_factory=factory,
            client_id="x",
            ticks=ticks,
        )
        # Construction succeeds — no I/O yet.
        assert client.state == ProtocolState.DISCONNECTED
        client.connect()
        # Factory error transitions to FAILED instead of propagating.
        assert client.state == ProtocolState.FAILED
        assert client.last_error is not None
        assert "factory failed" in str(client.last_error)

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
            ticks=ticks,
        )
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        # Force FAILED — simulate a wifi-drop that killed the socket.
        client.state = ProtocolState.FAILED
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

        client.state = ProtocolState.FAILED
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
            ticks=ticks,
        )
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED

        client.state = ProtocolState.FAILED
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
            ticks=ticks,
        )
        client.connect()
        _drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        initial_build_count = len(builds)

        client.disconnect()
        assert client.state == ProtocolState.DISCONNECTED

        # Force FAILED — even with the factory present, the user-driven
        # disconnect should keep self-heal off.
        client.state = ProtocolState.FAILED
        _drive(client, ticks, count=5)
        assert client.state == ProtocolState.FAILED
        assert len(builds) == initial_build_count  # factory not called again


class TestBoundedRecvPerTick:
    """``_read_inbound`` honors ``recv_budget_per_tick``.

    A 100 KB inbound PUBLISH would otherwise monopolize the tick
    while the kernel TCP buffer drains, and side tasks (LED blink,
    LCD update, control loop) would stutter.
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

    def test_default_cap_is_20_packets(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        ticks = FakeTicks()
        client = _new_client(sock, ticks)  # default cap
        assert client._max_tx_queue_size == 20  # noqa: SLF001 — pin the default

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
