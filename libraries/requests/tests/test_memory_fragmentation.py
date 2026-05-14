"""Cross-runtime heap-fragmentation regression tests for ResponseParser.

Runs on every runtime via the chumicro test harness (MicroPython /
CircuitPython unix-port) and via pytest (CPython).  Heap-state
assertions only fire on runtimes that expose ``gc.mem_free`` —
i.e. MP and CP — because this is a property of those allocators,
not of CPython's pymalloc.

Methodology — size-stratified free-block histogram
--------------------------------------------------

A naive "did the largest contiguous block shrink?" check misses
fragmentation that breaks middle-sized regions while leaving the
single biggest block intact.  Example: workload splits a 500 KB
free region into ten 50 KB blocks — ``largest`` (1 MB elsewhere)
doesn't move, but allocations in the 50 KB–500 KB range now fail
where they used to succeed.

To catch that, we sample **how many independent N-byte blocks the
heap can hold simultaneously** at five size tiers spanning the
parser's own working sizes (256 B header lines through 64 KB
response bodies).  Each tier is measured from a clean (post-collect)
heap, so the count is "how many ``size``-byte allocations would
currently succeed at once" — the metric that actually predicts
whether N-byte-class code will run.

Auto-GC remains enabled during the workload (we don't disable it):
production behavior is auto-managed GC, and disabling it during a
fragmentation test creates artificial heap pressure that's a test
artifact rather than something the parser would experience on a
device.  The earlier ``_largest_free_block``-based metric had a
sign bug (``baseline_gap - final_gap`` instead of the reverse) that
made it impossible to fail; replacing the metric outright avoids
inviting that class of bug back.

Hot paths exercised: ``_try_parse_status_line``,
``_try_parse_headers`` (slice-reassignment), ``_absorb_body_bytes``
(bytearray.extend growth), and chunked decode (per-chunk
staging).
"""

import gc

from chumicro_requests import ParseState, ResponseParser

# ---------------------------------------------------------------------------
# Runtime capability detection
# ---------------------------------------------------------------------------

_HAS_MEM_FREE = hasattr(gc, "mem_free")


# ---------------------------------------------------------------------------
# Size-stratified free-block histogram
# ---------------------------------------------------------------------------

#: Size tiers (bytes) we sample for fragmentation detection.  Spans the
#: parser's per-line scratch (~256 B), per-chunk scratch (~1–4 KB),
#: typical body buffer (16 KB), and full-response capacity (64 KB).
#: A drop at any tier between baseline and final indicates the workload
#: fragmented the heap in a way that prevents allocations of that size.
_FRAGMENTATION_TIERS = (256, 1024, 4096, 16384, 65536)


def _count_blocks_of_size(size):
    """Return how many independent ``size``-byte bytearrays we can hold.

    Allocates greedily until ``MemoryError``, counts, then frees + collects.
    This is the metric that actually predicts whether the next test can
    do its work: ``largest`` says nothing about how many independent
    free runs of that size exist.
    """
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
    """Return a ``{size: count}`` snapshot of allocatable-block availability."""
    return {size: _count_blocks_of_size(size) for size in tiers}


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


def _probe_workload_delta(workload, iterations,
                          leak_tolerance=4096,
                          tier_drop_tolerance=2):
    """Assert *workload* doesn't leak bytes or fragment any size tier.

    Baseline captured *after* the test's fixture setup, so the delta
    reflects only the workload itself — not whatever the test
    environment had already allocated.

    For each tier in :data:`_FRAGMENTATION_TIERS`, asserts that the
    drop in available-block count between baseline and final is at
    most *tier_drop_tolerance* blocks.  A drop > tolerance at any
    tier means the workload broke the heap's ability to satisfy
    allocations at that size class.

    On CPython (no ``mem_free``) the workload still runs as a
    smoke check but no heap assertions fire.
    """
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
# Tests
# ---------------------------------------------------------------------------


def test_small_body_no_leak_no_fragmentation():
    """50 small Content-Length cycles — sensor poll path."""
    response = _build_response(body_size=128, header_count=5)

    def workload():
        parser = _drive_parser(response, chunk_size=512)
        assert parser.state == ParseState.DONE

    _probe_workload_delta(workload, iterations=50)


def test_large_body_no_leak_no_fragmentation():
    """30 8 KiB-body cycles — exercises ``_absorb_body_bytes`` growth."""
    response = _build_response(body_size=8192, header_count=10)

    def workload():
        parser = _drive_parser(response, chunk_size=512)
        assert parser.state == ParseState.DONE

    _probe_workload_delta(workload, iterations=30)


def test_many_headers_no_leak_no_fragmentation():
    """30 cycles × 50 headers — slice-reassignment churn at full pressure.

    Each header line triggers ``self._buffer = bytearray(self._buffer[crlf+2:])``
    in ``_try_parse_headers``.  30 × 50 = 1500 transient bytearrays
    of decreasing size — the textbook small-fragment-generator
    pattern.  Earlier ratio-based test versions of this had to be
    dialed down to 20 × 30 because the workload would crash with
    MemoryError under late-preflight heap pressure (parser
    couldn't allocate 474 bytes despite 1.9 MB free).  That crash
    was an artifact of the test harness's fragmented heap, not of
    the parser — measurement showed the parser itself adds 0 bytes
    of fragmentation per cycle.

    Restored to 30 × 50 with delta-based assertions so the
    measurement is honest.  If this crashes in late-preflight, the
    fix is subprocess-per-file isolation in the harness, not
    dialing the workload down.
    """
    response = _build_response(body_size=64, header_count=50)

    def workload():
        parser = _drive_parser(response, chunk_size=128)
        assert parser.state == ParseState.DONE
        assert len(parser.headers) >= 50

    _probe_workload_delta(workload, iterations=30)


def test_chunked_no_leak_no_fragmentation():
    """30 chunked-encoded cycles — chunked decode + body assembly."""
    chunks = [b"a" * 256] * 10  # 2.5 KiB body in 10 chunks
    response = _build_chunked_response(chunks)

    def workload():
        parser = _drive_parser(response, chunk_size=128)
        assert parser.state == ParseState.DONE
        assert parser.body == b"a" * 2560

    _probe_workload_delta(workload, iterations=30)


def test_mixed_workload_no_leak_no_fragmentation():
    """Alternating small / large / chunked cycles — combined pressure."""
    small_response = _build_response(body_size=128, header_count=5)
    large_response = _build_response(body_size=4096, header_count=15)
    chunked_response = _build_chunked_response([b"a" * 256] * 5)
    responses = (small_response, large_response, chunked_response)

    def workload_factory():
        cycle_index = [0]

        def workload():
            response = responses[cycle_index[0] % 3]
            cycle_index[0] += 1
            parser = _drive_parser(response, chunk_size=256)
            assert parser.state == ParseState.DONE

        return workload

    _probe_workload_delta(workload_factory(), iterations=30)
