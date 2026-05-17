"""Host-side memory-pressure regression tests.

These tests run on CPython using :mod:`tracemalloc` to profile
per-operation allocations and :mod:`gc` to force a clean baseline
before each measurement.  They catch Python-level leaks in the
client / connection — leaks that survive cycles of
send/recv/ping/close without the session tearing down.

These don't replicate device-level fragmentation (CP / MP
allocators differ from CPython), but they prove the pure-Python
data structures the session maintains converge: any growing list /
dict / accumulating closure surfaces here as monotonically rising
allocation counts.

Pair with the live-board functional tests in
``libraries/websockets/functional_tests/`` for end-to-end
heap-fragmentation measurement against real hardware.

Why the library itself never calls ``gc.collect()``: fragmentation
is prevented by design (pre-allocated recv + frame-parser buffers,
bounded TX queue, no per-message data-structure growth in steady
state) and host-side leaks are caught here.  A library calling
``gc.collect()`` invisibly inside ``handle()`` would impose its
collect cadence on every other task in the system; the runner
contract (``handle`` returns quickly) keeps that decision in the
user's hands.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import struct
import tracemalloc

from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    OPCODE_BINARY,
    OPCODE_PONG,
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketServer,
    WebSocketState,
)
from chumicro_websockets._wire import encode_frame
from chumicro_websockets.testing import FakeConnection, FakeListener

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(socket: FakeConnection, clock: FakeTicks) -> WebSocketClient:
    return WebSocketClient(
        connection_factory=lambda *_args, **_kwargs: socket,
        ticks=clock,
    )


def _drive_client_to_open(client: WebSocketClient, socket: FakeConnection,
                          clock: FakeTicks) -> None:
    """Drive a client through its handshake until OPEN, using the same
    canned 101 the rest of the test suite uses."""
    client.connect("ws://example.com/")
    # Send handshake (drain in one or two ticks).
    while client.state == WebSocketState.CONNECTING:
        client.handle(clock.ticks_ms())
        request = socket.read_outbound()
        if not request:
            continue
        # Synthesize a matching 101 from the client's nonce.
        from chumicro_websockets._wire import (
            HandshakeRequestParser,
            encode_server_handshake_response,
        )
        parser = HandshakeRequestParser()
        parser.feed(request)
        response = encode_server_handshake_response(parser.client_key)
        socket.feed_inbound(response)
    assert client.state == WebSocketState.OPEN


def _measure_growth(operation, *, warmup_iterations=50, sample_iterations=500):
    """Run *operation* warmup_iterations times, then sample_iterations
    more, measuring how much heap memory accumulated AFTER GC.

    Returns ``(growth_bytes, current_kib, peak_kib)``.

    A clean implementation should produce growth_bytes near zero —
    every transient allocation gets reaped.  Significant positive
    growth indicates a leak.
    """
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


def _client_outbound_unmask(framed: bytes) -> tuple[int, bytes]:
    """Decode a single client-masked frame, returning (opcode, unmasked payload)."""
    first_byte = framed[0]
    second_byte = framed[1]
    opcode = first_byte & 0x0F
    payload_length = second_byte & 0x7F
    offset = 2
    if payload_length == 126:
        payload_length = struct.unpack("!H", framed[offset:offset + 2])[0]
        offset += 2
    elif payload_length == 127:
        payload_length = struct.unpack("!Q", framed[offset:offset + 8])[0]
        offset += 8
    mask_key = framed[offset:offset + 4]
    offset += 4
    masked = framed[offset:offset + payload_length]
    payload = bytes(
        masked[index] ^ mask_key[index & 3]
        for index in range(payload_length)
    )
    return opcode, payload


# ---------------------------------------------------------------------------
# send_text — the hottest outbound path
# ---------------------------------------------------------------------------


class TestSendTextNoLeak:
    def test_send_text_no_growth(self) -> None:
        """500 sequential send_text calls should not accumulate heap.

        Detects: lingering references in ``_tx_queue`` (queue items
        not popped), accumulating partial-send tuples in
        ``_tx_partial``, callback closures not garbage-collected.
        """
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)

        def operation() -> None:
            socket.outbound = bytearray()  # discard the wire bytes
            client.send_text("hello")
            client.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        # <2 KiB over 500 iterations is well within tracemalloc noise.
        assert growth_bytes < 2048, (
            f"send_text leaked {growth_bytes} bytes over 500 iterations"
        )


# ---------------------------------------------------------------------------
# send_binary — same path, larger payload
# ---------------------------------------------------------------------------


class TestSendBinaryNoLeak:
    def test_send_binary_no_growth(self) -> None:
        """500 binary sends with a 256-byte payload should not leak."""
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)

        payload = b"x" * 256

        def operation() -> None:
            socket.outbound = bytearray()
            client.send_binary(payload)
            client.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        assert growth_bytes < 4096, (
            f"send_binary leaked {growth_bytes} bytes over 500 iterations"
        )


# ---------------------------------------------------------------------------
# Inbound text receipt — exercises the framing pipeline
# ---------------------------------------------------------------------------


class TestInboundTextNoLeak:
    def test_inbound_text_no_growth(self) -> None:
        """500 inbound text frames should reuse the recv + frame parser
        buffers cleanly.

        Detects: payload bytes copied into a growing list, callback
        closures keeping references, frame parser buffer growing
        without bound.
        """
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)
        # Sink for the inbound text — drop reference immediately so
        # the test measures the framing-pipeline's own retention, not
        # the application's accumulation.
        client.on_text = lambda _text: None

        # Build a server-to-client frame once (no mask, since servers
        # MUST NOT mask outbound).  Reuse the same bytes 500x — the
        # FakeConnection's feed_inbound path makes its own copy via
        # bytearray.extend.
        frame = encode_frame(OPCODE_TEXT, b"21", fin=True, mask=None)

        def operation() -> None:
            socket.feed_inbound(frame)
            client.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        assert growth_bytes < 4096, (
            f"inbound text leaked {growth_bytes} bytes over 500 iterations"
        )


# ---------------------------------------------------------------------------
# Inbound binary receipt — larger payload + binary callback path
# ---------------------------------------------------------------------------


class TestInboundBinaryNoLeak:
    def test_inbound_binary_no_growth(self) -> None:
        """500 inbound binary frames with a 256-byte payload should not leak."""
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)
        client.on_binary = lambda _data: None

        frame = encode_frame(OPCODE_BINARY, b"x" * 256, fin=True, mask=None)

        def operation() -> None:
            socket.feed_inbound(frame)
            client.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        assert growth_bytes < 4096, (
            f"inbound binary leaked {growth_bytes} bytes over 500 iterations"
        )


# ---------------------------------------------------------------------------
# PING / PONG round-trip — control-frame path
# ---------------------------------------------------------------------------


class TestPingPongNoLeak:
    def test_ping_pong_round_trip_no_growth(self) -> None:
        """500 ping-then-pong cycles should not accumulate state.

        Detects: pong-deadline ticks not cleared, callback closures
        retained beyond pong, control-frame buffers not released.
        """
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)
        client.on_pong = lambda _data: None

        # The peer-side PONG echoing the client's PING.
        pong_frame = encode_frame(OPCODE_PONG, b"", fin=True, mask=None)

        def operation() -> None:
            socket.outbound = bytearray()
            client.send_ping(b"")
            client.handle(clock.ticks_ms())
            socket.feed_inbound(pong_frame)
            client.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=20, sample_iterations=300,
        )
        assert growth_bytes < 4096, (
            f"ping/pong round trip leaked {growth_bytes} bytes over 300 iterations"
        )
        # No outstanding ping after the cycle.
        assert client._pending_ping_deadline_ticks is None


# ---------------------------------------------------------------------------
# Pre-allocated buffer reuse
# ---------------------------------------------------------------------------


class TestRecvBufferReuse:
    def test_recv_buffer_id_stable(self) -> None:
        """The session's recv scratch buffer is allocated once + reused.

        Pulls 100 small inbound frames through; the underlying
        bytearray's id() must be stable.  Regression guard for the
        slice-G refactor (the recv_buffer pre-allocation lives on
        ``_BaseSession`` now).
        """
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)
        client.on_text = lambda _text: None

        frame = encode_frame(OPCODE_TEXT, b"x", fin=True, mask=None)

        buffer_ids = set()
        for _ in range(100):
            socket.feed_inbound(frame)
            client.handle(clock.ticks_ms())
            buffer_ids.add(id(client._recv_buffer))
        assert len(buffer_ids) == 1, "session reallocated its recv buffer mid-flight"

    def test_frame_parser_state_resets_cleanly(self) -> None:
        """The FrameParser's internal write cursors reset between frames.

        After parsing N frames the FrameParser's own ``_buffer`` is
        empty and the steady-state ``_payload`` is reused but its
        write cursor is back to zero — no across-frame retention.
        """
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)
        client.on_text = lambda _text: None

        frame = encode_frame(OPCODE_TEXT, b"hello", fin=True, mask=None)
        for _ in range(50):
            socket.feed_inbound(frame)
            client.handle(clock.ticks_ms())

        # Frame parser should be in READING_HEADER with the buffer
        # empty; the steady-state payload buffer is reused (len stays
        # at the buffer capacity) but the logical write cursor is 0.
        from chumicro_websockets._wire import FrameParseState
        parser = client._frame_parser
        assert parser.state == FrameParseState.READING_HEADER
        assert len(parser._buffer) == 0
        assert parser._payload is parser._payload_buffer
        assert parser._payload_write_offset == 0


# ---------------------------------------------------------------------------
# Bounded recv loop — handle() returns promptly with no inbound
# ---------------------------------------------------------------------------


class TestHandleBoundedWork:
    def test_handle_returns_promptly_with_no_data(self) -> None:
        """handle() with no inbound data should not spin.

        Asserts: a single recv_into call to discover "no data", then
        the handle() returns without churning.
        """
        socket = FakeConnection()
        clock = FakeTicks()
        client = _make_client(socket, clock)
        _drive_client_to_open(client, socket, clock)

        recv_calls: list[int] = []
        original_recv_into = socket.recv_into

        def counting_recv_into(buffer, nbytes: int = 0) -> int:
            recv_calls.append(1)
            return original_recv_into(buffer, nbytes)

        socket.recv_into = counting_recv_into  # type: ignore[assignment]
        client.handle(clock.ticks_ms())
        # One recv_into call to discover EAGAIN, then exit.
        assert len(recv_calls) == 1


# ---------------------------------------------------------------------------
# Server-side Connection — same patterns mirrored
# ---------------------------------------------------------------------------


def _make_server(listener: FakeListener, clock: FakeTicks,
                 *, on_connection) -> WebSocketServer:
    return WebSocketServer(
        listener=listener,
        on_connection=on_connection,
        ticks=clock,
    )


def _drive_server_to_open(socket: FakeConnection, server: WebSocketServer,
                          listener: FakeListener, clock: FakeTicks):
    """Accept a connection and drive its handshake to OPEN."""
    from chumicro_websockets._wire import (
        encode_client_handshake,
        make_websocket_key,
    )

    listener.queue_accept(socket)
    server.handle(clock.ticks_ms())  # accept
    assert server.connection_count == 1
    connection = server.connections[0]

    key = make_websocket_key()
    request = encode_client_handshake("example.com", 80, "/", key)
    socket.feed_inbound(request)
    while connection.state == WebSocketState.CONNECTING:
        connection.handle(clock.ticks_ms())
    return connection


class TestServerInboundNoLeak:
    def test_server_inbound_text_no_growth(self) -> None:
        """500 inbound text frames into a server Connection should not leak."""
        socket = FakeConnection()
        clock = FakeTicks()
        observed = []
        server = _make_server(
            FakeListener(),
            clock,
            on_connection=lambda connection: observed.append(connection),
        )
        connection = _drive_server_to_open(socket, server, server._listener, clock)
        connection.on_text = lambda _text: None

        # Client-side outbound MUST be masked.
        frame = encode_frame(OPCODE_TEXT, b"21", fin=True, mask=b"abcd")

        def operation() -> None:
            socket.feed_inbound(frame)
            connection.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        assert growth_bytes < 4096, (
            f"server inbound text leaked {growth_bytes} bytes over 500 iterations"
        )

    def test_server_send_text_no_growth(self) -> None:
        """500 outbound text frames from a server Connection should not leak."""
        socket = FakeConnection()
        clock = FakeTicks()
        observed = []
        server = _make_server(
            FakeListener(),
            clock,
            on_connection=lambda connection: observed.append(connection),
        )
        connection = _drive_server_to_open(socket, server, server._listener, clock)

        def operation() -> None:
            socket.outbound = bytearray()
            connection.send_text("ack")
            connection.handle(clock.ticks_ms())

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=500,
        )
        assert growth_bytes < 2048, (
            f"server send_text leaked {growth_bytes} bytes over 500 iterations"
        )
