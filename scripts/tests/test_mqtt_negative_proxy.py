"""Unit tests for scripts/mqtt_negative_proxy.py.

Two surfaces are exercised:

* the MQTT frame classifier (:class:`PubackFilter` and
  :func:`decode_remaining_length`) — PUBACK detection across split TCP
  segments and remaining-length varint edges; and
* the blackhole / forward state machine (:class:`ProxyConnection`) — driven
  over in-process ``socket.socketpair()`` pairs so no ports are bound.

The control-command dispatch is checked directly on a :class:`NegativeProxy`
instance (its ``__init__`` opens no listening sockets).
"""

from __future__ import annotations

import select
import socket
import struct
import time
from collections.abc import Callable, Iterator

import pytest
from mqtt_negative_proxy import (
    Controller,
    NegativeProxy,
    ProxyConfig,
    ProxyConnection,
    ProxyFrameError,
    PubackFilter,
    decode_remaining_length,
)

# --------------------------------------------------------------------------
# Frame builders (independent of the module under test, so a bug in the
# module's own encoders can't mask a decode bug).
# --------------------------------------------------------------------------


def _varint(length: int) -> bytes:
    out = bytearray()
    while True:
        digit = length & 0x7F
        length >>= 7
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


def _frame(type_byte: int, body: bytes) -> bytes:
    return bytes([type_byte]) + _varint(len(body)) + body


def _puback(packet_id: int) -> bytes:
    return _frame(0x40, struct.pack(">H", packet_id))


def _publish(topic: str, payload: bytes, packet_id: int) -> bytes:
    encoded_topic = topic.encode()
    body = struct.pack(">H", len(encoded_topic)) + encoded_topic + struct.pack(">H", packet_id) + payload
    return _frame(0x30 | 0x02, body)


# --------------------------------------------------------------------------
# decode_remaining_length: varint edges
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("encoded", "value", "consumed"),
    [
        (b"\x00", 0, 1),
        (b"\x7f", 127, 1),
        (b"\x80\x01", 128, 2),
        (b"\xff\x7f", 16383, 2),
        (b"\x80\x80\x01", 16384, 3),
        (b"\xff\xff\x7f", 2097151, 3),
        (b"\x80\x80\x80\x01", 2097152, 4),
        (b"\xff\xff\xff\x7f", 268435455, 4),
    ],
)
def test_decode_remaining_length_edges(encoded: bytes, value: int, consumed: int) -> None:
    assert decode_remaining_length(encoded) == (value, consumed)


def test_decode_remaining_length_respects_start_offset() -> None:
    assert decode_remaining_length(b"\x40\x80\x01", 1) == (128, 2)


@pytest.mark.parametrize("partial", [b"", b"\x80", b"\x80\x80", b"\x80\x80\x80"])
def test_decode_remaining_length_incomplete_returns_zero(partial: bytes) -> None:
    assert decode_remaining_length(partial) == (None, 0)


def test_decode_remaining_length_malformed_raises() -> None:
    # Four continuation bytes: the varint never terminates within MQTT's cap.
    with pytest.raises(ProxyFrameError):
        decode_remaining_length(b"\x80\x80\x80\x80")


# --------------------------------------------------------------------------
# PubackFilter: classification and split-segment alignment
# --------------------------------------------------------------------------


def test_publish_forwarded_unchanged_regardless_of_flag() -> None:
    frame = _publish("bake/flood", b"hello", 7)
    assert PubackFilter().feed(frame, drop_pubacks=True) == frame
    assert PubackFilter().feed(frame, drop_pubacks=False) == frame


def test_puback_dropped_when_flag_on() -> None:
    filt = PubackFilter()
    assert filt.feed(_puback(9), drop_pubacks=True) == b""
    assert filt.frames_dropped == 1
    assert filt.frames_forwarded == 0


def test_puback_forwarded_when_flag_off() -> None:
    frame = _puback(9)
    filt = PubackFilter()
    assert filt.feed(frame, drop_pubacks=False) == frame
    assert filt.frames_forwarded == 1
    assert filt.frames_dropped == 0


def test_puback_dropped_across_byte_by_byte_segments() -> None:
    filt = PubackFilter()
    collected = bytearray()
    for byte in _puback(0x1234):
        collected += filt.feed(bytes([byte]), drop_pubacks=True)
    assert collected == b""
    assert filt.frames_dropped == 1


def test_publish_reassembled_when_split_mid_varint() -> None:
    # A payload of 200 forces a 2-byte remaining-length varint; split the
    # stream right between the two varint bytes.
    frame = _publish("t", b"y" * 200, 3)
    split = 2  # after type byte + first varint byte
    filt = PubackFilter()
    out = filt.feed(frame[:split], drop_pubacks=True)
    out += filt.feed(frame[split:], drop_pubacks=True)
    assert out == frame
    assert filt.frames_forwarded == 1


def test_mixed_stream_drops_only_pubacks() -> None:
    stream = _publish("a", b"1", 1) + _puback(1) + _publish("a", b"2", 2) + _puback(2)
    filt = PubackFilter()
    out = filt.feed(stream, drop_pubacks=True)
    assert out == _publish("a", b"1", 1) + _publish("a", b"2", 2)
    assert filt.frames_dropped == 2
    assert filt.frames_forwarded == 2


def test_mixed_stream_survives_arbitrary_chunking() -> None:
    stream = _publish("a", b"payload-one", 1) + _puback(1) + _publish("a", b"two", 2) + _puback(2)
    expected = _publish("a", b"payload-one", 1) + _publish("a", b"two", 2)
    for chunk_size in (1, 2, 3, 5, 7, 11):
        filt = PubackFilter()
        out = bytearray()
        for start in range(0, len(stream), chunk_size):
            out += filt.feed(stream[start : start + chunk_size], drop_pubacks=True)
        assert bytes(out) == expected, f"chunk_size={chunk_size}"
        assert filt.frames_dropped == 2


def test_zero_length_body_frame_forwarded() -> None:
    pingresp = b"\xd0\x00"
    filt = PubackFilter()
    assert filt.feed(pingresp, drop_pubacks=True) == pingresp
    assert filt.frames_forwarded == 1


def test_large_payload_forwarded_intact() -> None:
    frame = _publish("bake/big", b"z" * 4096, 42)
    filt = PubackFilter()
    out = bytearray()
    for start in range(0, len(frame), 500):
        out += filt.feed(frame[start : start + 500], drop_pubacks=True)
    assert bytes(out) == frame
    assert filt.frames_forwarded == 1


def test_drop_decision_latched_at_header_completion() -> None:
    # Header (with drop on) completes in the first feed; the body arrives in
    # a later feed with drop off.  The frame must still be dropped: the
    # decision is latched when the header completes, so a mid-body toggle
    # cannot truncate a frame.
    frame = _puback(0x0501)
    filt = PubackFilter()
    assert filt.feed(frame[:2], drop_pubacks=True) == b""  # header only
    assert filt.feed(frame[2:], drop_pubacks=False) == b""  # body, flag flipped
    assert filt.frames_dropped == 1


def test_malformed_remaining_length_raises_from_feed() -> None:
    filt = PubackFilter()
    with pytest.raises(ProxyFrameError):
        filt.feed(b"\x40\x80\x80\x80\x80", drop_pubacks=True)


# --------------------------------------------------------------------------
# ProxyConnection: blackhole / forward state machine over socketpairs
# --------------------------------------------------------------------------

ConnBundle = tuple[ProxyConnection, socket.socket, socket.socket, Controller]


@pytest.fixture
def make_conn() -> Iterator[Callable[..., ConnBundle]]:
    """Factory building a ProxyConnection wired to two socketpairs.

    Returns ``(conn, board_peer, broker_peer, controller)``:

    * write into *board_peer* to simulate the board sending; ``pump(conn.board)``
      then forwards to the broker side, readable from *broker_peer*;
    * write into *broker_peer* to simulate the broker sending; ``pump(conn.broker)``
      forwards (post-filter) to the board side, readable from *board_peer*.
    """
    created: list[socket.socket] = []

    def factory(controller: Controller | None = None) -> ConnBundle:
        controller = controller or Controller()
        board_proxy, board_peer = socket.socketpair()
        broker_proxy, broker_peer = socket.socketpair()
        created.extend([board_proxy, board_peer, broker_proxy, broker_peer])
        conn = ProxyConnection(
            conn_id=1, board=board_proxy, broker=broker_proxy, controller=controller
        )
        return conn, board_peer, broker_peer, controller

    yield factory
    for sock in created:
        sock.close()


def _read_available(sock: socket.socket, timeout: float = 0.5) -> bytes:
    ready, _, _ = select.select([sock], [], [], timeout)
    if not ready:
        return b""
    return sock.recv(65536)


def test_board_to_broker_forwards(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    board_peer.sendall(b"CONNECT-bytes")
    assert conn.pump(conn.board) is True
    assert _read_available(broker_peer) == b"CONNECT-bytes"
    assert controller.bytes_c2b_recv == len(b"CONNECT-bytes")
    assert controller.bytes_c2b_fwd == len(b"CONNECT-bytes")


def test_broker_to_client_forwards(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    frame = _publish("bake", b"data", 1)
    broker_peer.sendall(frame)
    assert conn.pump(conn.broker) is True
    assert _read_available(board_peer) == frame
    assert controller.bytes_b2c_fwd == len(frame)
    assert controller.frames_forwarded == 1


def test_blackhole_silently_drops_board_to_broker(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.blackhole = True
    # Board sends; proxy must receive-and-discard, keep the connection alive.
    board_peer.sendall(b"published-bytes")
    assert conn.pump(conn.board) is True  # connection stays open
    assert _read_available(broker_peer, timeout=0.1) == b""  # nothing forwarded
    assert controller.bytes_c2b_recv == len(b"published-bytes")
    assert controller.bytes_c2b_fwd == 0


def test_blackhole_silently_drops_broker_to_client(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.blackhole = True
    broker_peer.sendall(_publish("bake", b"data", 1))
    assert conn.pump(conn.broker) is True
    assert _read_available(board_peer, timeout=0.1) == b""
    assert controller.bytes_b2c_recv > 0
    assert controller.bytes_b2c_fwd == 0
    assert controller.frames_forwarded == 0


def test_drop_puback_eats_ack_forwards_publish(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.drop_puback = True
    publish = _publish("bake", b"data", 5)
    broker_peer.sendall(publish + _puback(5))
    assert conn.pump(conn.broker) is True
    assert _read_available(board_peer) == publish  # PUBLISH through, PUBACK eaten
    assert controller.frames_dropped == 1
    assert controller.frames_forwarded == 1


def test_board_to_broker_unaffected_by_drop_puback(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.drop_puback = True  # only affects broker->client
    board_peer.sendall(_puback(1))  # a PUBACK travelling board->broker is still forwarded
    assert conn.pump(conn.board) is True
    assert _read_available(broker_peer) == _puback(1)


def test_pump_reports_dead_on_board_eof(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, _broker_peer, _controller = make_conn()
    board_peer.close()
    assert conn.pump(conn.board) is False


def test_pump_reports_dead_on_broker_eof(make_conn: Callable[..., ConnBundle]) -> None:
    conn, _board_peer, broker_peer, _controller = make_conn()
    broker_peer.close()
    assert conn.pump(conn.broker) is False


# --------------------------------------------------------------------------
# Control-command dispatch (no sockets bound)
# --------------------------------------------------------------------------


@pytest.fixture
def proxy() -> Iterator[NegativeProxy]:
    instance = NegativeProxy(ProxyConfig())
    try:
        yield instance
    finally:
        instance.selector.close()


def test_dispatch_blackhole_toggles_flag(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("blackhole on") == "ok blackhole on"
    assert proxy.controller.blackhole is True
    assert proxy._dispatch("blackhole off") == "ok blackhole off"
    assert proxy.controller.blackhole is False


def test_dispatch_drop_puback_toggles_flag(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("drop-puback on") == "ok drop-puback on"
    assert proxy.controller.drop_puback is True
    assert proxy._dispatch("DROP-PUBACK OFF") == "ok drop-puback off"  # case-insensitive
    assert proxy.controller.drop_puback is False


def test_dispatch_bad_argument_is_error(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("blackhole maybe").startswith("err usage")
    assert proxy.controller.blackhole is False


def test_dispatch_unknown_command_is_error(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("frobnicate").startswith("err unknown command")


def test_dispatch_kill_with_no_connections(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("kill") == "ok killed 0"


def test_dispatch_stat_reports_flags(proxy: NegativeProxy) -> None:
    proxy.controller.drop_puback = True
    line = proxy._dispatch("stat")
    assert "drop_puback=on" in line
    assert "pubacks_dropped=0" in line


def test_dispatch_reset_stats_zeroes_counters(proxy: NegativeProxy) -> None:
    proxy.controller.bytes_c2b_recv = 999
    proxy.controller.frames_dropped = 5
    assert proxy._dispatch("reset-stats") == "ok reset-stats"
    assert proxy.controller.bytes_c2b_recv == 0
    assert proxy.controller.frames_dropped == 0


def test_dispatch_quit_closes_session(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("quit") is None


def test_dispatch_empty_line_is_noop(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("") == ""


# --------------------------------------------------------------------------
# delay command: dispatch surface (A9 — slow broker)
# --------------------------------------------------------------------------


def test_dispatch_delay_defaults_to_both(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay 4000") == "ok delay 4000 both"
    assert proxy.controller.delay_c2b_ms == 4000
    assert proxy.controller.delay_b2c_ms == 4000


def test_dispatch_delay_b2c_only(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay 4000 b2c") == "ok delay 4000 b2c"
    assert proxy.controller.delay_b2c_ms == 4000
    assert proxy.controller.delay_c2b_ms == 0  # c2b untouched


def test_dispatch_delay_c2b_only(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay 250 c2b") == "ok delay 250 c2b"
    assert proxy.controller.delay_c2b_ms == 250
    assert proxy.controller.delay_b2c_ms == 0


def test_dispatch_delay_off_clears_both(proxy: NegativeProxy) -> None:
    proxy.controller.delay_c2b_ms = proxy.controller.delay_b2c_ms = 4000
    assert proxy._dispatch("delay off") == "ok delay 0 both"
    assert proxy.controller.delay_c2b_ms == 0
    assert proxy.controller.delay_b2c_ms == 0


def test_dispatch_delay_zero_clears_named_direction(proxy: NegativeProxy) -> None:
    proxy.controller.delay_c2b_ms = proxy.controller.delay_b2c_ms = 4000
    assert proxy._dispatch("delay 0 b2c") == "ok delay 0 b2c"
    assert proxy.controller.delay_b2c_ms == 0
    assert proxy.controller.delay_c2b_ms == 4000  # c2b left engaged


def test_dispatch_delay_bad_value_is_error(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay soon").startswith("err usage")
    assert proxy.controller.delay_b2c_ms == 0


def test_dispatch_delay_negative_is_error(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay -5").startswith("err usage")


def test_dispatch_delay_bad_direction_is_error(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay 100 sideways").startswith("err usage")
    assert proxy.controller.delay_b2c_ms == 0


def test_dispatch_delay_missing_value_is_error(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("delay").startswith("err usage")


def test_stat_line_reports_delays(proxy: NegativeProxy) -> None:
    proxy._dispatch("delay 4000 b2c")
    line = proxy._dispatch("stat")
    assert "delay_b2c=4000" in line
    assert "delay_c2b=0" in line


# --------------------------------------------------------------------------
# delay data-plane: queue-then-release, ordering, per-direction (A9)
# --------------------------------------------------------------------------


def test_delay_b2c_queues_instead_of_forwarding(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.delay_b2c_ms = 200
    frame = _publish("bake", b"data", 1)
    before = time.monotonic()
    broker_peer.sendall(frame)
    assert conn.pump(conn.broker) is True
    # Nothing forwarded yet; the chunk is parked with a future release instant.
    assert _read_available(board_peer, timeout=0.1) == b""
    release = conn.next_release()
    assert release is not None
    assert release >= before + 0.2  # held at least the configured delay
    assert controller.bytes_b2c_fwd == 0  # not counted as forwarded until released


def test_delay_release_forwards_after_hold(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.delay_b2c_ms = 200
    frame = _publish("bake", b"data", 1)
    broker_peer.sendall(frame)
    assert conn.pump(conn.broker) is True
    release = conn.next_release()
    assert release is not None
    # Before the release instant: still held.
    assert conn.flush_due(release - 0.05) is True
    assert _read_available(board_peer, timeout=0.05) == b""
    # At/after the release instant: forwarded intact.
    assert conn.flush_due(release) is True
    assert _read_available(board_peer) == frame
    assert controller.bytes_b2c_fwd == len(frame)
    assert conn.next_release() is None  # queue drained


def test_delay_preserves_order_across_chunks(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.delay_b2c_ms = 100
    first = _publish("a", b"one", 1)
    second = _publish("a", b"two", 2)
    broker_peer.sendall(first)
    assert conn.pump(conn.broker) is True
    broker_peer.sendall(second)
    assert conn.pump(conn.broker) is True
    # Both parked; release everything and assert FIFO ordering on the wire.
    assert conn.flush_due(time.monotonic() + 1.0) is True
    assert _read_available(board_peer) == first + second


def test_delay_c2b_direction_queues_board_to_broker(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.delay_c2b_ms = 200
    board_peer.sendall(b"CONNECT-bytes")
    assert conn.pump(conn.board) is True
    assert _read_available(broker_peer, timeout=0.1) == b""  # held
    assert conn.flush_due(time.monotonic() + 1.0) is True
    assert _read_available(broker_peer) == b"CONNECT-bytes"


def test_delay_only_affects_selected_direction(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.delay_b2c_ms = 500  # only broker->client is slowed
    board_peer.sendall(b"CONNECT-bytes")
    assert conn.pump(conn.board) is True
    assert _read_available(broker_peer) == b"CONNECT-bytes"  # c2b still immediate
    assert conn.next_release() is None


def test_delay_send_failure_tears_down(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    controller.delay_b2c_ms = 100
    broker_peer.sendall(_publish("bake", b"data", 1))
    assert conn.pump(conn.broker) is True
    board_peer.close()  # destination gone before the release fires
    conn.board.close()
    assert conn.flush_due(time.monotonic() + 1.0) is False


# --------------------------------------------------------------------------
# NegativeProxy delay scheduling: select-timeout + flush loop (A9)
# --------------------------------------------------------------------------


def _register(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle], conn_id: int
) -> ConnBundle:
    """Build a connection on the proxy's controller and register it."""
    conn, board_peer, broker_peer, _ = make_conn(proxy.controller)
    conn.conn_id = conn_id
    proxy._connections[conn_id] = conn
    proxy.controller.connections_active += 1
    proxy.controller.connections_total += 1
    return conn, board_peer, broker_peer, proxy.controller


def test_select_timeout_default_without_pending(proxy: NegativeProxy) -> None:
    assert proxy._select_timeout() == 1.0


def test_select_timeout_shortens_for_pending(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    conn, _board_peer, broker_peer, _ = _register(proxy, make_conn, 1)
    proxy.controller.delay_b2c_ms = 300
    broker_peer.sendall(_publish("a", b"x", 1))
    assert conn.pump(conn.broker) is True
    timeout = proxy._select_timeout()
    assert 0.0 < timeout <= 0.3  # capped at the nearest release, not the 1 s idle


def test_flush_delayed_releases_past_due(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    conn, board_peer, _broker_peer, _ = _register(proxy, make_conn, 1)
    frame = _publish("a", b"x", 1)
    conn._pending_b2c.append((time.monotonic() - 1.0, frame))  # already overdue
    proxy._flush_delayed()
    assert _read_available(board_peer) == frame
    assert conn.next_release() is None


def test_flush_delayed_holds_future_items(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    conn, board_peer, _broker_peer, _ = _register(proxy, make_conn, 1)
    frame = _publish("a", b"x", 1)
    conn._pending_b2c.append((time.monotonic() + 100.0, frame))
    proxy._flush_delayed()
    assert _read_available(board_peer, timeout=0.05) == b""
    assert conn.next_release() is not None


# --------------------------------------------------------------------------
# freeze-existing / thaw: per-connection freeze scoping (A7)
# --------------------------------------------------------------------------


def test_dispatch_freeze_existing_no_connections(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("freeze-existing") == "ok froze 0"


def test_dispatch_thaw_no_connections(proxy: NegativeProxy) -> None:
    assert proxy._dispatch("thaw") == "ok thawed 0"


def test_freeze_existing_freezes_only_current_connections(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    existing, _, _, _ = _register(proxy, make_conn, 1)
    assert proxy._dispatch("freeze-existing") == "ok froze 1"
    assert existing.frozen is True
    # A connection opened AFTER the freeze must pass through unfaulted — this
    # is the A7 property the global blackhole can't provide.
    fresh, _, _, _ = _register(proxy, make_conn, 2)
    assert fresh.frozen is False


def test_freeze_then_fresh_connection_forwards(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    frozen_conn, frozen_board, frozen_broker, _ = _register(proxy, make_conn, 1)
    proxy._dispatch("freeze-existing")
    fresh_conn, fresh_board, fresh_broker, _ = _register(proxy, make_conn, 2)
    # Frozen connection discards both directions...
    frozen_board.sendall(b"ghost-publish")
    assert frozen_conn.pump(frozen_conn.board) is True
    assert _read_available(frozen_broker, timeout=0.1) == b""
    # ...while the fresh re-dial reaches the broker cleanly.
    fresh_board.sendall(b"fresh-connect")
    assert fresh_conn.pump(fresh_conn.board) is True
    assert _read_available(fresh_broker) == b"fresh-connect"


def test_thaw_restores_forwarding(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    conn, board_peer, broker_peer, _ = _register(proxy, make_conn, 1)
    proxy._dispatch("freeze-existing")
    assert proxy._dispatch("thaw") == "ok thawed 1"
    assert conn.frozen is False
    board_peer.sendall(b"after-thaw")
    assert conn.pump(conn.board) is True
    assert _read_available(broker_peer) == b"after-thaw"


def test_frozen_connection_discards_both_directions(make_conn: Callable[..., ConnBundle]) -> None:
    conn, board_peer, broker_peer, controller = make_conn()
    conn.frozen = True
    board_peer.sendall(b"c2b-bytes")
    assert conn.pump(conn.board) is True  # socket stays open
    assert _read_available(broker_peer, timeout=0.1) == b""
    broker_peer.sendall(_publish("bake", b"data", 1))
    assert conn.pump(conn.broker) is True
    assert _read_available(board_peer, timeout=0.1) == b""
    assert controller.bytes_c2b_fwd == 0
    assert controller.bytes_b2c_fwd == 0


def test_frozen_connection_still_detects_peer_close(make_conn: Callable[..., ConnBundle]) -> None:
    # A frozen connection discards data but must still notice a real FIN/RST —
    # the broker evicting the ghost (A7) has to tear the connection down.
    conn, _board_peer, broker_peer, _ = make_conn()
    conn.frozen = True
    broker_peer.close()
    assert conn.pump(conn.broker) is False


def test_frozen_connection_holds_broker_leg_on_board_close(
    make_conn: Callable[..., ConnBundle],
) -> None:
    # The literal A7 ghost: a self-healing board CLOSES its dead socket
    # before re-dialing.  A frozen connection must swallow that FIN rather
    # than propagate it, so the broker still holds the stale session when
    # the same-client_id re-dial arrives (MUST_DISCONNECT_EXISTING).
    conn, board_peer, _broker_peer, _ = make_conn()
    conn.frozen = True
    board_peer.close()
    assert conn.pump(conn.board) is True  # connection survives
    assert conn.board_gone is True
    assert "half_open=1" in conn.stat_line()


def test_unfrozen_connection_still_tears_down_on_board_close(
    make_conn: Callable[..., ConnBundle],
) -> None:
    # The half-open hold is freeze-scoped: a normal board disconnect must
    # keep tearing the whole connection down.
    conn, board_peer, _broker_peer, _ = make_conn()
    board_peer.close()
    assert conn.pump(conn.board) is False
    assert conn.board_gone is False


def test_thaw_tears_down_half_open_ghosts(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    # A ghost whose board leg is gone cannot resume forwarding; thaw reaps it.
    conn, board_peer, _broker_peer, _ = _register(proxy, make_conn, 1)
    proxy._dispatch("freeze-existing")
    board_peer.close()
    assert conn.pump(conn.board) is True
    assert proxy._dispatch("thaw") == "ok thawed 1"
    assert conn.conn_id not in proxy._connections


# --------------------------------------------------------------------------
# stat: per-connection visibility (A7 assertion surface)
# --------------------------------------------------------------------------


def test_stat_report_lists_each_connection(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    _register(proxy, make_conn, 1)
    _register(proxy, make_conn, 2)
    report = proxy._dispatch("stat")
    lines = report.splitlines()
    assert lines[0].startswith("blackhole=")  # global summary first
    assert "conns_active=2" in lines[0]
    conn_lines = [line for line in lines if line.startswith("conn id=")]
    assert len(conn_lines) == 2
    assert any("id=1" in line for line in conn_lines)
    assert any("id=2" in line for line in conn_lines)


def test_stat_report_shows_frozen_and_byte_counts(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    conn, board_peer, broker_peer, _ = _register(proxy, make_conn, 1)
    board_peer.sendall(b"hello-broker")
    assert conn.pump(conn.board) is True
    proxy._dispatch("freeze-existing")
    conn_line = next(
        line for line in proxy._dispatch("stat").splitlines() if line.startswith("conn id=1")
    )
    assert "frozen=1" in conn_line
    assert f"c2b_recv={len(b'hello-broker')}" in conn_line
    assert f"c2b_fwd={len(b'hello-broker')}" in conn_line


def test_stat_report_reports_pending_delay_depth(
    proxy: NegativeProxy, make_conn: Callable[..., ConnBundle]
) -> None:
    conn, _board_peer, broker_peer, _ = _register(proxy, make_conn, 1)
    proxy.controller.delay_b2c_ms = 500
    broker_peer.sendall(_publish("a", b"x", 1))
    assert conn.pump(conn.broker) is True
    conn_line = next(
        line for line in proxy._dispatch("stat").splitlines() if line.startswith("conn id=1")
    )
    assert "pend_b2c=1" in conn_line
