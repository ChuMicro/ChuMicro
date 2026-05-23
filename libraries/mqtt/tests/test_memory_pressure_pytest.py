"""Host-side memory-pressure regression tests.

These tests run on CPython using :mod:`tracemalloc` to profile per-
operation allocations and :mod:`gc` to force a clean baseline before
each measurement.  They catch Python-level leaks in the client itself,
the kind that survive cycles of publish/subscribe/recv without the
client tearing down.

These don't replicate device-level fragmentation (CP / MP allocators
are different), but they prove the pure-Python data structures the
client maintains converge: any growing list / dict / accumulating
closure surfaces here as monotonically rising allocation counts.
"""

#: CPython-only lane (pytest fixtures / host stdlib).  Not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import tracemalloc

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_puback_bytes,
    canned_publish_bytes,
    canned_suback_bytes,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def _connect_client(client: MQTTClient, sock: FakeSocket, ticks: FakeTicks) -> None:
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client.connect()
    client.handle(ticks.ticks_ms())
    client.handle(ticks.ticks_ms())
    assert client.state == ProtocolState.CONNECTED


def _new_client(sock: FakeSocket, ticks: FakeTicks) -> MQTTClient:
    return MQTTClient(
        sock,
        client_id="perf-test",
        keep_alive_seconds=60,
        ticks=ticks,
    )


def _measure_growth(operation, *, warmup_iterations=50, sample_iterations=500):
    """Run *operation* warmup_iterations times, then sample_iterations
    more, measuring how much heap memory accumulated AFTER GC.

    Returns ``(growth_bytes, current_kib, peak_kib)``.

    The warmup runs to fill any one-shot caches (re.compile, etc) so
    the sample period measures only steady-state per-iteration cost.

    A clean implementation of *operation* should produce growth_bytes
    near zero (every transient allocation gets reaped).  Significant
    positive growth indicates a leak.
    """
    # Force a GC pass + start from a stable baseline.
    gc.collect()
    tracemalloc.start()
    try:
        for _ in range(warmup_iterations):
            operation()
        gc.collect()
        baseline_current, _baseline_peak = tracemalloc.get_traced_memory()

        for _ in range(sample_iterations):
            operation()
        gc.collect()
        final_current, final_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    growth = final_current - baseline_current
    return growth, final_current / 1024, final_peak / 1024


# ---------------------------------------------------------------------------
# QoS 0 publish: the hottest path on a typical sensor
# ---------------------------------------------------------------------------


class TestPublishQos0NoLeak:
    def test_qos0_publish_no_growth(self) -> None:
        """500 sequential QoS 0 publishes should not accumulate heap.

        Detects: lingering references in ``_tx_queue`` (queue items
        not popped), ``_in_flight`` allocations on QoS 0 (would be a
        bug), accumulating ``_pending_responses``, callback closures
        not garbage-collected.
        """
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        _connect_client(client, sock, ticks)

        def operation() -> None:
            sock.sent.clear()
            client.publish("topic/qos0", b"payload", qos=0)
            client.handle(ticks.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        # Allow some slack for tracemalloc bookkeeping itself.  <2 KiB
        # over 500 iterations is well within the noise floor on
        # Python 3.14.
        assert growth_bytes < 2048, (
            f"QoS 0 publish leaked {growth_bytes} bytes over 500 iterations"
        )


# ---------------------------------------------------------------------------
# QoS 1 publish: exercises in-flight table churn
# ---------------------------------------------------------------------------


class TestPublishQos1NoLeak:
    def test_qos1_publish_then_puback_no_growth(self) -> None:
        """500 QoS 1 publishes with matching PUBACKs should not leak.

        Detects: in-flight entries not discarded on PUBACK, callback
        closures retained beyond ack, packet-id allocator leaking ids.
        """
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        _connect_client(client, sock, ticks)

        # We pre-allocate one packet-id per iteration's expected
        # PUBACK.  After each publish, the client allocated 1 id.
        # After the matching PUBACK, the id is freed.  Steady-state.

        def operation() -> None:
            sock.sent.clear()
            client.publish("topic/qos1", b"payload", qos=1)
            client.handle(ticks.ticks_ms())
            # Find the just-allocated packet_id and synthesize its PUBACK.
            in_flight_ids = list(client._in_flight.keys())
            assert len(in_flight_ids) == 1
            sock.enqueue_recv(canned_puback_bytes(packet_id=in_flight_ids[0]))
            client.handle(ticks.ticks_ms())

        growth_bytes, current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=20, sample_iterations=300,
        )
        assert growth_bytes < 4096, (
            f"QoS 1 publish/puback leaked {growth_bytes} bytes over 300 iterations "
            f"(final tracked={current_kib:.1f} KiB)"
        )
        # In-flight table should be empty after each round trip.
        assert len(client._in_flight) == 0


# ---------------------------------------------------------------------------
# Inbound publish receipt: exercises decoder buffer reuse
# ---------------------------------------------------------------------------


class TestInboundReceiveNoLeak:
    def test_qos0_inbound_no_growth(self) -> None:
        """500 inbound QoS 0 messages should reuse the RX buffer cleanly.

        Detects: payload bytes copied into a growing list, callback
        closures keeping references, decoder buffer growing without
        bound.
        """
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        _connect_client(client, sock, ticks)
        # Drop the message-handler reference cycle by using a
        # function that doesn't capture a list.  Drains the bytes
        # but doesn't accumulate.
        client.on_message = lambda topic, payload: None

        def operation() -> None:
            sock.enqueue_recv(canned_publish_bytes("temp", b"21", qos=0))
            client.handle(ticks.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        assert growth_bytes < 4096, (
            f"inbound QoS 0 leaked {growth_bytes} bytes over 500 iterations"
        )


# ---------------------------------------------------------------------------
# Long subscribe/unsubscribe cycle
# ---------------------------------------------------------------------------


class TestSubscribeUnsubscribeNoLeak:
    def test_subscribe_unsubscribe_cycle_no_growth(self) -> None:
        """Subscribe/SUBACK/Unsubscribe/UNSUBACK 200 times should not leak."""
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        _connect_client(client, sock, ticks)

        from chumicro_mqtt.testing import canned_unsuback_bytes  # noqa: PLC0415

        def operation() -> None:
            sock.sent.clear()  # FakeSocket accumulates sent bytes, not the client's leak
            client.subscribe("topic/x", qos=0)
            sub_id = client._pending_responses[-1].packet_id
            client.handle(ticks.ticks_ms())
            sock.enqueue_recv(canned_suback_bytes(packet_id=sub_id, granted_qos=0))
            client.handle(ticks.ticks_ms())
            client.unsubscribe("topic/x")
            unsub_id = client._pending_responses[-1].packet_id
            client.handle(ticks.ticks_ms())
            sock.enqueue_recv(canned_unsuback_bytes(packet_id=unsub_id))
            client.handle(ticks.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=20, sample_iterations=200,
        )
        assert growth_bytes < 4096, (
            f"subscribe/unsubscribe cycle leaked {growth_bytes} bytes over 200 iterations"
        )
        assert len(client._pending_responses) == 0
        assert len(client._in_flight) == 0


# ---------------------------------------------------------------------------
# Pre-allocated buffer reuse
# ---------------------------------------------------------------------------


class TestRxBufferReuse:
    def test_decoder_buffer_capacity_constant(self) -> None:
        """The decoder's steady-state buffer is allocated once + reused.

        Pulls 100 small inbound packets through.  The underlying
        bytearray's id() must be stable.
        """
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        _connect_client(client, sock, ticks)
        client.on_message = lambda topic, payload: None

        # The decoder lives at client._decoder.  Its internal buffer
        # is _buffer (private but stable across the lifetime).
        buffer_ids = set()
        for _ in range(100):
            sock.enqueue_recv(canned_publish_bytes("t", b"x", qos=0))
            client.handle(ticks.ticks_ms())
            buffer_ids.add(id(client._decoder._buffer))
        assert len(buffer_ids) == 1, "decoder reallocated its RX buffer mid-flight"


# ---------------------------------------------------------------------------
# Latency / call-count instrumentation
# ---------------------------------------------------------------------------


class TestRecvLoopBoundedWork:
    def test_handle_returns_promptly_with_no_data(self) -> None:
        """``handle()`` exits promptly when the socket has no data.

        The recv loop's exit condition is ``recv_into`` returning 0,
        not "got < capacity" (the latter would short-circuit before
        TCP fragmentation finished feeding a multi-packet burst, which
        breaks concurrent QoS 1).  This test asserts the empty-queue
        case exits after a single ``recv_into`` rather than spinning.
        """
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _new_client(sock, ticks)
        _connect_client(client, sock, ticks)

        # Time-cheap proxy: count recv_into calls.
        recv_calls: list[int] = []
        original_recv_into = sock.recv_into

        def counting_recv_into(buffer: bytearray, nbytes: int = 0) -> int:
            recv_calls.append(1)
            return original_recv_into(buffer, nbytes)

        sock.recv_into = counting_recv_into  # type: ignore[assignment]
        client.handle(ticks.ticks_ms())
        # One recv_into call to discover "no data", then the loop exits.
        assert len(recv_calls) == 1
