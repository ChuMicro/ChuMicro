"""Cross-runtime heap-fragmentation regression tests for WebSocketClient.

See :mod:`chumicro_requests.tests.test_memory_fragmentation` for the
methodology — same delta-based pattern, baseline captured AFTER
fixture setup so the assertion measures only what the workload
itself contributes.

Current coverage: inbound frame parsing.  Outbound coverage
(``send_text`` / ``send_binary`` / ``send_ping`` + pong round-trip)
deferred — those paths hit ``BlockingIOError`` inside
:func:`chumicro_websockets._session._is_eagain`, which is a CPython
builtin not available on MicroPython.  Tracking + fix queued in
``plans/next-up.md``.
"""

import gc
import hashlib

from chumicro_test_harness import skip
from chumicro_websockets import (
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketState,
)
from chumicro_websockets._wire import (
    HandshakeRequestParser,
    encode_frame,
    encode_server_handshake_response,
)
from chumicro_websockets.testing import FakeConnection, TickClock

# CircuitPython unix-port's hashlib only exposes sha256 — no sha1, no
# hashlib.new().  The WebSocket handshake requires SHA-1 (RFC 6455
# §1.3), so the WebSocketClient handshake itself can't run on that
# runtime regardless of what this test does.  The fragmentation tests
# below detect this at module load and become no-ops on runtimes
# where the library's handshake can't complete.  Tracking +
# pure-Python SHA-1 fallback queued in ``plans/next-up.md``.
_HAS_SHA1 = hasattr(hashlib, "sha1") or hasattr(hashlib, "new")

# ---------------------------------------------------------------------------
# Runtime capability detection
# ---------------------------------------------------------------------------

_HAS_MEM_FREE = hasattr(gc, "mem_free")


# ---------------------------------------------------------------------------
# Size-stratified free-block histogram + delta-based assertion helper
# ---------------------------------------------------------------------------

_FRAGMENTATION_TIERS = (256, 1024, 4096, 16384, 65536)


def _count_blocks_of_size(size):
    gc.collect()
    holders = []
    try:
        while True:
            holders.append(bytearray(size))
    except MemoryError:
        pass
    count = len(holders)
    del holders
    gc.collect()
    return count


def _free_block_histogram(tiers=_FRAGMENTATION_TIERS):
    return {size: _count_blocks_of_size(size) for size in tiers}


def _probe_workload_delta(workload, iterations,
                          leak_tolerance=4096,
                          tier_drop_tolerance=2):
    if not _HAS_MEM_FREE:
        for _ in range(iterations):
            workload()
        return

    gc.collect()
    baseline_free = gc.mem_free()
    baseline_histogram = _free_block_histogram()

    for _ in range(iterations):
        workload()
    gc.collect()

    final_free = gc.mem_free()
    final_histogram = _free_block_histogram()

    bytes_consumed = baseline_free - final_free

    assert bytes_consumed <= leak_tolerance, (
        f"workload consumed {bytes_consumed} bytes over {iterations} iterations "
        f"(baseline_free={baseline_free}, final_free={final_free}, "
        f"leak_tolerance={leak_tolerance})"
    )

    for size, baseline_count in baseline_histogram.items():
        final_count = final_histogram[size]
        drop = baseline_count - final_count
        assert drop <= tier_drop_tolerance, (
            f"workload fragmented {size}-byte tier over {iterations} "
            f"iterations: baseline={baseline_count} blocks, "
            f"final={final_count} blocks, drop={drop} blocks "
            f"(tier_drop_tolerance={tier_drop_tolerance}). "
            f"baseline_histogram={baseline_histogram}, "
            f"final_histogram={final_histogram}"
        )


# ---------------------------------------------------------------------------
# Test client setup
# ---------------------------------------------------------------------------


def _make_client(socket, clock):
    return WebSocketClient(
        connection_factory=lambda *_args, **_kwargs: socket,
        ticks_ms_func=clock.now,
        ticks_add_func=clock.add,
        ticks_diff_func=clock.diff,
    )


def _drive_to_open(client, socket, clock):
    """Drive a fresh client through its handshake to OPEN."""
    client.connect("ws://example.com/")
    while client.state == WebSocketState.CONNECTING:
        client.handle(clock.now())
        request = socket.read_outbound()
        if not request:
            continue
        parser = HandshakeRequestParser()
        parser.feed(request)
        response = encode_server_handshake_response(parser.client_key)
        socket.feed_inbound(response)
    assert client.state == WebSocketState.OPEN


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_inbound_text_no_leak_no_fragmentation():
    """30 inbound unmasked text frames — frame parser ``_buffer`` reuse.

    Drives the inbound recv path: each tick the FakeConnection feeds
    a server-to-client text frame, ``client.handle`` runs the frame
    parser to completion, the on_text callback fires (and discards),
    and the parser's internal buffer should reset for the next frame.
    """
    if not _HAS_SHA1:
        # CP unix-port lacks ``hashlib.sha1`` and ``hashlib.new`` — the
        # WebSocket handshake (RFC 6455 §1.3) can't complete here.
        skip("requires hashlib.sha1 — CP unix-port omits it")
    socket = FakeConnection()
    clock = TickClock()
    client = _make_client(socket, clock)
    _drive_to_open(client, socket, clock)
    client.on_text = lambda _text: None

    # Servers MUST NOT mask outbound frames — encode once, replay.
    frame = encode_frame(OPCODE_TEXT, b"21", fin=True, mask=None)

    def workload():
        socket.feed_inbound(frame)
        client.handle(clock.now())

    _probe_workload_delta(workload, iterations=30)
