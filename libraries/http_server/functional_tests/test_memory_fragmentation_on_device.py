"""On-device heap-fragmentation regression for RequestParser.

Mirrors ``libraries/http_server/tests/test_memory_fragmentation.py`` but
runs on real CP/MP hardware via the chumicro test-harness.  Parser-only
(no sockets, no listening server) — feeds canned request bytes through
RequestParser and asserts the heap doesn't fragment.

Tier sizes (256 / 1024 / 4096) are scaled for the ~150 KB working
heap of a Pi Pico W or ESP32-S2.  See the response-side test
(``libraries/requests/functional_tests/test_memory_fragmentation_on_device.py``)
for the methodology rationale.
"""

import gc
import sys

from chumicro_http_server._wire import RequestParser, RequestParseState

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


def test_small_request_no_leak_no_fragmentation_on_device():
    """8 small GET requests — typical sensor-poll inbound path.

    Requires ``--chumicro-deploy-mode flash``; see the response-side
    test for why RAM mode OOMs the bootstrap on Pi Pico W.
    """
    request = _build_request(target="/api/v1/state", header_count=3)

    def workload():
        parser = _drive_parser(request, chunk_size=128)
        assert parser.state == RequestParseState.DONE

    _probe_workload_delta(workload, iterations=8)


def test_post_with_body_no_leak_no_fragmentation_on_device():
    """5 POSTs with 1 KiB body — exercises ``_absorb_body_bytes``."""
    request = _build_request(method="POST", target="/api/v1/data",
                             body_size=1024, header_count=5)

    def workload():
        parser = _drive_parser(request, chunk_size=256)
        assert parser.state == RequestParseState.DONE
        assert len(parser.body) == 1024

    _probe_workload_delta(workload, iterations=5)


def test_many_headers_no_leak_no_fragmentation_on_device():
    """8 cycles × 12 headers — slice-reassignment churn."""
    request = _build_request(header_count=12)

    def workload():
        parser = _drive_parser(request, chunk_size=128)
        assert parser.state == RequestParseState.DONE
        # Host + 12 X-Custom = 13 headers.
        assert len(parser.headers) >= 12

    _probe_workload_delta(workload, iterations=8)


def test_mixed_request_shapes_no_leak_no_fragmentation_on_device():
    """Alternating small / POST-with-body / many-header requests."""
    small = _build_request(target="/", header_count=3)
    posty = _build_request(method="POST", target="/data",
                           body_size=512, header_count=4)
    bigheaders = _build_request(target="/big", header_count=8)
    requests = (small, posty, bigheaders)

    cycle_index = [0]

    def workload():
        request = requests[cycle_index[0] % 3]
        cycle_index[0] += 1
        parser = _drive_parser(request, chunk_size=128)
        assert parser.state == RequestParseState.DONE

    _probe_workload_delta(workload, iterations=8)
