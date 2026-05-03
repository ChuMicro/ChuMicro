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

from chumicro_http_server._wire import RequestParser, RequestParseState

# ---------------------------------------------------------------------------
# Runtime capability detection
# ---------------------------------------------------------------------------

_HAS_MEM_FREE = hasattr(gc, "mem_free")


# ---------------------------------------------------------------------------
# Largest-contiguous-block probe + delta-based assertion helper
# ---------------------------------------------------------------------------


def _largest_free_block(upper_hint):
    gc.collect()
    low = 0
    high = upper_hint
    best = 0
    while low <= high:
        mid = (low + high) // 2
        try:
            probe = bytearray(mid)
        except MemoryError:
            high = mid - 1
        else:
            best = mid
            del probe
            gc.collect()
            low = mid + 1
    return best


def _probe_workload_delta(workload, iterations,
                          leak_tolerance=4096,
                          fragmentation_tolerance=4096):
    if not _HAS_MEM_FREE:
        for _ in range(iterations):
            workload()
        return

    gc.collect()
    baseline_free = gc.mem_free()
    baseline_largest = _largest_free_block(baseline_free)

    for _ in range(iterations):
        workload()
    gc.collect()

    final_free = gc.mem_free()
    final_largest = _largest_free_block(final_free)

    bytes_consumed = baseline_free - final_free
    holes_added = (baseline_free - baseline_largest) - (final_free - final_largest)

    assert bytes_consumed <= leak_tolerance, (
        f"workload consumed {bytes_consumed} bytes over {iterations} iterations "
        f"(baseline_free={baseline_free}, final_free={final_free}, "
        f"leak_tolerance={leak_tolerance})"
    )
    assert holes_added <= fragmentation_tolerance, (
        f"workload added {holes_added} bytes of fragmentation over {iterations} "
        f"iterations (baseline_largest={baseline_largest}, "
        f"final_largest={final_largest}, fragmentation_tolerance={fragmentation_tolerance})"
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
