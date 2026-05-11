"""On-device heap-fragmentation regression for ResponseParser.

Mirrors ``libraries/requests/tests/test_memory_fragmentation.py`` but
runs on real CP/MP hardware via the chumicro test-harness.  Parser-only
(no wifi, no sockets, no live HTTP) — feeds canned response bytes
through ResponseParser and asserts the heap doesn't fragment.

Why a separate functional test
------------------------------

The cross-runtime unit test runs on the unix-port (~2 MB heap, 64-bit
allocator), where the parser's allocation patterns are easily handled
by GC.  Real microcontroller boards (Pi Pico W: 195 KB heap; ESP32-S2:
~150 KB; rp2 / esp32 allocator quirks) are where fragmentation actually
bites.  This test exercises the same parser shapes against the real
allocator and validates the metric on production conditions.

Tier sizes are scaled for a ~150 KB working heap: 256 / 1024 / 4096
bytes.  Larger tiers (16 KB+) hold too few blocks to be informative
on this heap class; the 64-byte tier holds thousands of blocks where
1–3-block churn is allocator entropy, not fragmentation signal.
"""

import gc
import sys

from chumicro_requests import ParseState, ResponseParser

# ---------------------------------------------------------------------------
# Histogram metric (mirrors the unit test, scaled for small heaps)
# ---------------------------------------------------------------------------

_FRAGMENTATION_TIERS = (256, 1024, 4096)

# Tier-drop tolerance was originally 4 (calibrated against an idealised
# allocator).  Live-board runs on Lolin S2 show that even no-op iterations
# drop 8-20 blocks at the 1024-byte tier purely from allocator entropy
# (the histogram itself allocates / frees, the test harness allocates
# log strings, GC timing varies).  A real fragmentation bug shows drops
# in the hundreds (a parser retaining one 1 KB buffer per iteration over
# 8 iterations would lose ~8 blocks but also grow ``bytes_consumed`` by
# ~8 KB — the leak-tolerance check catches it instead).  Per-runtime
# leak tolerances reflect MP's mark-sweep + 16-byte block allocator
# running ~50 % more entropy than CP on the same hardware.
if sys.implementation.name == "micropython":
    _DEFAULT_LEAK_TOLERANCE = 4096
else:
    _DEFAULT_LEAK_TOLERANCE = 2048
_DEFAULT_TIER_DROP_TOLERANCE = 32


def _count_blocks_of_size(size):
    """Return how many independent ``size``-byte bytearrays we can hold."""
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
    """Run *workload* *iterations* times; assert no leak + no tier drop.

    Defaults are runtime-aware: MicroPython's mark-sweep allocator runs
    ~50 % more entropy than CircuitPython on the same Lolin S2 hardware,
    so the MP defaults are 2 KB / 12 blocks higher.  Override per-test
    if a workload genuinely needs tighter (or looser) bounds.
    """
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
# Builders + parser driver
# ---------------------------------------------------------------------------


def _build_response(*, body_size, header_count=5):
    parts = [b"HTTP/1.1 200 OK\r\n"]
    for index in range(header_count):
        parts.append(f"X-Custom-{index}: value-{index}\r\n".encode())
    parts.append(f"Content-Length: {body_size}\r\n".encode())
    parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
    parts.append(b"x" * body_size)
    return b"".join(parts)


def _build_chunked_response(chunks):
    parts = [b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"]
    for chunk in chunks:
        parts.append(f"{len(chunk):x}\r\n".encode())
        parts.append(chunk)
        parts.append(b"\r\n")
    parts.append(b"0\r\n\r\n")
    return b"".join(parts)


def _drive_parser(response_bytes, chunk_size=512):
    parser = ResponseParser()
    offset = 0
    length = len(response_bytes)
    while offset < length and parser.state != ParseState.DONE:
        end = offset + chunk_size
        if end > length:
            end = length
        parser.feed(response_bytes[offset:end])
        offset = end
    return parser


# ---------------------------------------------------------------------------
# Tests — requires ``--deploy-mode flash``.
#
# RAM mode sends the test source inline through the serial REPL, which
# eats ~2× the file size of working heap on Pi Pico W and OOMs the
# CircuitPython bootstrap before any test runs.  Flash mode copies the
# file to the device filesystem and exec's it from there.
#
# Workload sizes are calibrated for Pi Pico W (~150 KB working heap).
# Bigger workloads belong in the cross-runtime unit tests on unix-port.
# What we want here is "does the parser, on a real small-heap board,
# leave behind any tier-class block damage?" — repetition counts are
# sized so auto-GC has headroom to fire between iterations.
# ---------------------------------------------------------------------------


def test_small_body_no_leak_no_fragmentation_on_device():
    """8 small Content-Length cycles — sensor-poll path."""
    response = _build_response(body_size=64, header_count=3)

    def workload():
        parser = _drive_parser(response, chunk_size=128)
        assert parser.state == ParseState.DONE

    _probe_workload_delta(workload, iterations=8)


def test_large_body_no_leak_no_fragmentation_on_device():
    """5 1 KiB-body cycles — exercises ``_absorb_body_bytes`` growth."""
    response = _build_response(body_size=1024, header_count=5)

    def workload():
        parser = _drive_parser(response, chunk_size=256)
        assert parser.state == ParseState.DONE

    _probe_workload_delta(workload, iterations=5)


def test_many_headers_no_leak_no_fragmentation_on_device():
    """8 cycles × 12 headers — slice-reassign churn at moderate pressure."""
    response = _build_response(body_size=32, header_count=12)

    def workload():
        parser = _drive_parser(response, chunk_size=128)
        assert parser.state == ParseState.DONE
        assert len(parser.headers) >= 12

    _probe_workload_delta(workload, iterations=8)


def test_chunked_no_leak_no_fragmentation_on_device():
    """5 chunked-encoded cycles — chunked decode + body assembly."""
    chunks = [b"a" * 64] * 4  # 256 B body in 4 chunks
    response = _build_chunked_response(chunks)

    def workload():
        parser = _drive_parser(response, chunk_size=64)
        assert parser.state == ParseState.DONE
        assert parser.body == b"a" * 256

    _probe_workload_delta(workload, iterations=5)


def test_mixed_workload_no_leak_no_fragmentation_on_device():
    """Alternating small / chunked cycles — combined pressure."""
    small_response = _build_response(body_size=64, header_count=3)
    chunked_response = _build_chunked_response([b"a" * 64] * 3)
    responses = (small_response, chunked_response)

    cycle_index = [0]

    def workload():
        response = responses[cycle_index[0] % 2]
        cycle_index[0] += 1
        parser = _drive_parser(response, chunk_size=128)
        assert parser.state == ParseState.DONE

    _probe_workload_delta(workload, iterations=8)
