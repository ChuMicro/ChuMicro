"""On-device heap-fragmentation regression for the WebSocket frame parser.

Mirrors ``libraries/websockets/tests/test_memory_fragmentation.py`` but
runs on real CP/MP hardware via the chumicro test-harness.

Drives :class:`chumicro_websockets._wire.FrameParser` directly — same
shape as the request/response on-device fragmentation tests: feed
canned wire bytes, verify FRAME_READY, drop the parser.  No
``WebSocketClient``, no ``FakeConnection``, no fake clock.  The
fragmentation-prone code (per-frame ``self._buffer`` slice-reassign +
``self._payload`` extend) lives in :class:`FrameParser`, so testing it
directly removes every layer between the bytes and the allocator.

Tier sizes (256 / 1024 / 4096) match the request/response on-device
fragmentation tests — scaled for the ~150 KB working heap of a Pi Pico W
or ESP32-S2.
"""

import gc
import sys

from chumicro_websockets import OPCODE_BINARY, OPCODE_TEXT
from chumicro_websockets._wire import FrameParser, FrameParseState, encode_frame

# ---------------------------------------------------------------------------
# Histogram metric
# ---------------------------------------------------------------------------

_FRAGMENTATION_TIERS = (256, 1024, 4096)

# Tolerances calibrated against live-board allocator entropy — see
# ``libraries/requests/functional_tests/test_memory_fragmentation_on_device.py``
# for the rationale.
if sys.implementation.name == "micropython":
    _DEFAULT_LEAK_TOLERANCE = 4096
else:
    _DEFAULT_LEAK_TOLERANCE = 2048
_DEFAULT_TIER_DROP_TOLERANCE = 32


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
                          leak_tolerance=_DEFAULT_LEAK_TOLERANCE,
                          tier_drop_tolerance=_DEFAULT_TIER_DROP_TOLERANCE):
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
        f"workload consumed {bytes_consumed} B over {iterations} iters "
        f"(baseline_free={baseline_free}, final_free={final_free}, "
        f"leak_tolerance={leak_tolerance})"
    )

    for size, baseline_count in baseline_histogram.items():
        final_count = final_histogram[size]
        drop = baseline_count - final_count
        assert drop <= tier_drop_tolerance, (
            f"workload fragmented {size}-byte tier over {iterations} "
            f"iters: baseline={baseline_count} blocks, "
            f"final={final_count} blocks, drop={drop} "
            f"(tier_drop_tolerance={tier_drop_tolerance}). "
            f"baseline={baseline_histogram}, final={final_histogram}"
        )


# ---------------------------------------------------------------------------
# Frame-parser driver
# ---------------------------------------------------------------------------


def _drive_frame_parser(frame_bytes, chunk_size=64):
    """Feed *frame_bytes* through a fresh :class:`FrameParser` in chunks."""
    parser = FrameParser()
    offset = 0
    length = len(frame_bytes)
    while offset < length and parser.state not in (
        FrameParseState.FRAME_READY,
        FrameParseState.ERROR,
    ):
        end = offset + chunk_size
        if end > length:
            end = length
        parser.feed(frame_bytes[offset:end])
        offset = end
    return parser


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_short_text_frame_no_leak_no_fragmentation_on_device():
    """8 unmasked 16-byte text frames — minimal-overhead frame churn.

    Requires ``--deploy-mode flash``.  Server-to-client traffic
    is unmasked (RFC 6455 §5.3).  Encoded once outside the loop; each
    iteration drives a fresh parser to completion.
    """
    frame = encode_frame(OPCODE_TEXT, b"x" * 16, fin=True, mask=None)

    def workload():
        parser = _drive_frame_parser(frame, chunk_size=64)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_TEXT
        assert len(parser.payload) == 16

    _probe_workload_delta(workload, iterations=8)


def test_medium_text_frame_no_leak_no_fragmentation_on_device():
    """8 unmasked 128-byte text frames — exercises payload buffering.

    128 B is large enough to force ``self._payload`` bytearray growth
    yet small enough to fit Pi Pico W's working heap across the loop.
    """
    frame = encode_frame(OPCODE_TEXT, b"x" * 128, fin=True, mask=None)

    def workload():
        parser = _drive_frame_parser(frame, chunk_size=64)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_TEXT
        assert len(parser.payload) == 128

    _probe_workload_delta(workload, iterations=8)


def test_masked_binary_frame_no_leak_no_fragmentation_on_device():
    """5 masked 128-byte binary frames — client-receives-masked path.

    Client-to-server traffic IS masked.  When something on this device
    parses incoming masked frames (server side), the parser walks
    READING_MASK before READING_PAYLOAD and unmasks per-byte during
    payload buffering.  Tests that the unmask loop doesn't fragment.
    """
    frame = encode_frame(OPCODE_BINARY, b"\xab" * 128, fin=True,
                         mask=b"\x12\x34\x56\x78")

    def workload():
        parser = _drive_frame_parser(frame, chunk_size=64)
        assert parser.state == FrameParseState.FRAME_READY
        assert parser.opcode == OPCODE_BINARY
        assert parser.had_mask is True
        assert len(parser.payload) == 128

    _probe_workload_delta(workload, iterations=5)


def test_reset_and_reuse_no_leak_no_fragmentation_on_device():
    """8 cycles of parser-then-reset — the long-lived parser path.

    A real connection holds one ``FrameParser`` for the full session
    and calls :meth:`reset` between frames.  This shape stresses the
    ``self._buffer = bytearray()`` reset path, which is a different
    fragmentation profile than fresh-parser-per-frame.
    """
    frame = encode_frame(OPCODE_TEXT, b"y" * 64, fin=True, mask=None)
    parser = FrameParser()

    def workload():
        offset = 0
        length = len(frame)
        while offset < length and parser.state not in (
            FrameParseState.FRAME_READY,
            FrameParseState.ERROR,
        ):
            end = offset + 32
            if end > length:
                end = length
            parser.feed(frame[offset:end])
            offset = end
        assert parser.state == FrameParseState.FRAME_READY
        assert len(parser.payload) == 64
        parser.reset()

    _probe_workload_delta(workload, iterations=8)
