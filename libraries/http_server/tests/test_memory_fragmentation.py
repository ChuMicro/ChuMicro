"""Cross-runtime heap-fragmentation regression tests for RequestParser.

See :mod:`chumicro_requests.tests.test_memory_fragmentation` for the
methodology — same delta-based pattern, baseline captured AFTER
fixture setup so the assertion measures only what the workload
itself contributes.

The :class:`RequestParser` mirrors :class:`chumicro_requests.ResponseParser`'s
streaming design (slice-reassignment in headers, bytearray.extend
in body), so it shares the same fragmentation profile — measurement
shows 0 bytes added per cycle on both clean and primed heaps.
"""

import gc
import sys

from chumicro_http_server._wire import RequestParser, RequestParseState
from chumicro_test_harness import skip

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
    if sys.implementation.name == "micropython" and sys.platform not in (
        "linux",
        "darwin",
        "win32",
    ):
        # The free-block histogram allocates bytearrays until
        # MemoryError across five size tiers — unbounded-time on a
        # constrained MicroPython interpreter (it wedged a Lolin S2
        # MP copy-mode sweep).  Covered on CPython, CircuitPython,
        # and the fast MicroPython unix-port; loud-skip on a real
        # MicroPython board.
        skip(
            "heap-fragmentation histogram is unbounded-time on a "
            "constrained MicroPython device"
        )
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
# Builders + parser driver
# ---------------------------------------------------------------------------


def _build_request(*, method="GET", target="/", body_size=0, header_count=5):
    parts = [f"{method} {target} HTTP/1.1\r\n".encode()]
    parts.append(b"Host: test\r\n")
    for index in range(header_count):
        parts.append(f"X-Custom-{index}: value-{index}\r\n".encode())
    if body_size > 0:
        parts.append(f"Content-Length: {body_size}\r\n".encode())
        parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
        parts.append(b"x" * body_size)
    else:
        parts.append(b"\r\n")
    return b"".join(parts)


def _drive_parser(request_bytes, chunk_size=512):
    parser = RequestParser()
    offset = 0
    length = len(request_bytes)
    while offset < length and parser.state != RequestParseState.DONE:
        end = offset + chunk_size
        if end > length:
            end = length
        parser.feed(request_bytes[offset:end])
        offset = end
    return parser


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_small_request_no_leak_no_fragmentation():
    """50 small GET requests — typical browser/sensor poll path."""
    request = _build_request(target="/api/v1/state", header_count=5)

    def workload():
        parser = _drive_parser(request, chunk_size=512)
        assert parser.state == RequestParseState.DONE

    _probe_workload_delta(workload, iterations=50)


def test_post_with_body_no_leak_no_fragmentation():
    """30 POSTs with 4 KiB body — exercises ``_absorb_body_bytes``."""
    request = _build_request(method="POST", target="/api/v1/data",
                             body_size=4096, header_count=8)

    def workload():
        parser = _drive_parser(request, chunk_size=512)
        assert parser.state == RequestParseState.DONE
        assert len(parser.body) == 4096

    _probe_workload_delta(workload, iterations=30)


def test_many_headers_no_leak_no_fragmentation():
    """30 cycles × 50 headers — slice-reassignment churn at full pressure.

    Same workload shape as the response-side many-headers test in
    ``chumicro_requests.tests.test_memory_fragmentation``, applied
    against the request-side parser.  Delta-based assertion measures
    the workload's contribution independent of harness heap state.
    """
    request = _build_request(header_count=50)

    def workload():
        parser = _drive_parser(request, chunk_size=128)
        assert parser.state == RequestParseState.DONE
        # Host + 50 X-Custom = 51 headers.
        assert len(parser.headers) >= 50

    _probe_workload_delta(workload, iterations=30)


def test_mixed_request_shapes_no_leak_no_fragmentation():
    """Alternating small / POST-with-body / many-header requests."""
    small = _build_request(target="/", header_count=3)
    posty = _build_request(method="POST", target="/data",
                           body_size=2048, header_count=5)
    bigheaders = _build_request(target="/big", header_count=15)
    requests = (small, posty, bigheaders)

    def workload_factory():
        cycle_index = [0]

        def workload():
            request = requests[cycle_index[0] % 3]
            cycle_index[0] += 1
            parser = _drive_parser(request, chunk_size=256)
            assert parser.state == RequestParseState.DONE

        return workload

    _probe_workload_delta(workload_factory(), iterations=30)
