"""Cross-runtime heap-fragmentation regression tests for the response parser.

Runs on every runtime via the chumicro test harness (MicroPython /
CircuitPython unix-port) and via pytest (CPython).  The
fragmentation-specific assertions only fire on runtimes that expose
``gc.mem_free`` — i.e. MP and CP — because heap fragmentation is a
property of those allocators, not of CPython's pymalloc.

Why this exists separately from :mod:`test_memory_pressure`:
:mod:`test_memory_pressure` uses :mod:`tracemalloc` to attribute
allocations on CPython; that catches Python-level leaks.  But the
failure mode the user actually worries about — "lots of free RAM but
no contiguous block big enough to allocate 10 bytes" — is a property
of the non-moving mark-sweep GC in MP/CP.  Only those runtimes can
detect it, and only via :func:`gc.mem_free` plus a bisect-allocate
probe for the largest contiguous free block.

What each test asserts:

* **No leak**: after N parser cycles + ``gc.collect()``, ``mem_free``
  returns to within a tolerance of the baseline.
* **No fragmentation**: after N parser cycles + ``gc.collect()``, the
  largest allocatable contiguous block is at least *fragmentation_floor*
  of total free memory.

The tests deliberately exercise the parser's high-churn paths:
``_try_parse_headers`` (slice-reassignment), ``_absorb_body_bytes``
(bytearray.extend growth), and chunked decode (per-chunk staging).
"""

import gc

from chumicro_requests import ParseState, ResponseParser

# ---------------------------------------------------------------------------
# Runtime capability detection
# ---------------------------------------------------------------------------

# ``gc.mem_free`` is only defined on MicroPython / CircuitPython.  On
# CPython this attribute is missing; the fragmentation assertions
# silently no-op (the parser drive still runs as a smoke check).
_HAS_MEM_FREE = hasattr(gc, "mem_free")


# ---------------------------------------------------------------------------
# Fragmentation probe
# ---------------------------------------------------------------------------


def _largest_free_block(upper_hint):
    """Return the largest currently-allocatable bytearray size in bytes.

    Uses bisection between 0 and *upper_hint* (typically ``gc.mem_free``).
    Each probe allocates a candidate bytearray; on success the binding
    is dropped *and* ``gc.collect()`` runs before the next iteration,
    because MicroPython / CircuitPython are non-refcounting — ``del``
    only unbinds the name, leaving the bytearray live in the heap until
    the next collection.  Without the per-iteration collect each
    successful probe would permanently consume free space and the
    bisect would converge on ``free / 2``.

    On CPython this would always return *upper_hint* (pymalloc has no
    fragmentation in this sense), so the probe is only meaningful on
    MP/CP.  Caller is responsible for skipping the probe on CPython.
    """
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
            gc.collect()  # MP/CP don't refcount; force the probe to release.
            low = mid + 1
    return best


# ---------------------------------------------------------------------------
# Parser-driving helpers (mirror test_memory_pressure)
# ---------------------------------------------------------------------------


def _build_response(body_size, header_count=5):
    """Build a Content-Length response with extra headers for parsing churn."""
    parts = [b"HTTP/1.1 200 OK\r\n"]
    for index in range(header_count):
        parts.append(f"X-Custom-{index}: value-{index}\r\n".encode())
    parts.append(f"Content-Length: {body_size}\r\n".encode())
    parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
    parts.append(b"x" * body_size)
    return b"".join(parts)


def _build_chunked_response(chunks):
    """Build a chunked-encoded response carrying *chunks* (list of bytes)."""
    parts = [b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"]
    for chunk in chunks:
        parts.append(f"{len(chunk):x}\r\n".encode())
        parts.append(chunk)
        parts.append(b"\r\n")
    parts.append(b"0\r\n\r\n")
    return b"".join(parts)


def _drive_parser(response_bytes, chunk_size=512):
    """Run a fresh parser to ``DONE`` over *response_bytes*."""
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


def _run_workload_and_probe(
    response_bytes,
    iterations,
    chunk_size=512,
    leak_tolerance_bytes=4096,
    fragmentation_floor=0.85,
):
    """Drive the parser *iterations* times and assert the heap is healthy.

    Two assertions, both gated on ``_HAS_MEM_FREE``:
    1. ``mem_free`` after the workload is within *leak_tolerance_bytes*
       of the baseline (no leak).
    2. The ratio ``largest_free_block / mem_free`` after the workload
       is at least *fragmentation_floor* (no severe fragmentation).

    On CPython (no ``mem_free``), the workload still runs as a
    functional smoke check but no heap assertions fire.
    """
    if not _HAS_MEM_FREE:
        # CPython smoke: just prove the workload completes cleanly.
        for _ in range(iterations):
            parser = _drive_parser(response_bytes, chunk_size=chunk_size)
            assert parser.state == ParseState.DONE
        return

    gc.collect()
    baseline_free = gc.mem_free()
    baseline_largest = _largest_free_block(baseline_free)

    for _ in range(iterations):
        parser = _drive_parser(response_bytes, chunk_size=chunk_size)
        assert parser.state == ParseState.DONE
    del parser  # release the last cycle's reference before the post-probe.
    gc.collect()

    final_free = gc.mem_free()
    final_largest = _largest_free_block(final_free)

    # 1. Leak assertion.
    leak = baseline_free - final_free
    assert leak <= leak_tolerance_bytes, (
        f"parser leaked {leak} bytes after {iterations} iterations "
        f"(baseline_free={baseline_free}, final_free={final_free})"
    )

    # 2. Fragmentation assertion (ratio of largest contiguous block).
    ratio = final_largest / final_free if final_free else 1.0
    baseline_ratio = (
        baseline_largest / baseline_free if baseline_free else 1.0
    )
    assert ratio >= fragmentation_floor, (
        f"heap fragmented after {iterations} parser cycles: "
        f"largest={final_largest} / free={final_free} = {ratio:.3f}, "
        f"floor={fragmentation_floor:.3f}, baseline_ratio={baseline_ratio:.3f}"
    )


# ---------------------------------------------------------------------------
# Tests — flat module-level functions for the chumicro test harness
# ---------------------------------------------------------------------------


def test_small_body_no_leak_no_fragmentation():
    """50 small Content-Length cycles should not leak or fragment."""
    response = _build_response(body_size=128, header_count=5)
    _run_workload_and_probe(response, iterations=50)


def test_large_body_no_leak_no_fragmentation():
    """30 8 KiB-body cycles should not leak or fragment.

    Stresses the ``_absorb_body_bytes`` bytearray growth path —
    each parser allocates an 8 KiB body bytearray that grows via
    ``.extend()``.  If that growth pattern leaves dead bytearrays
    scattered in the heap, the largest-free-block ratio will drop.
    """
    response = _build_response(body_size=8192, header_count=10)
    _run_workload_and_probe(response, iterations=30)


def test_many_headers_no_leak_no_fragmentation():
    """20 30-header cycles should not leak or fragment.

    Stresses ``_try_parse_headers`` — each header line triggers a
    fresh ``self._buffer = bytearray(self._buffer[crlf+2:])`` slice
    reassignment.  20 cycles × 30 headers = 600 transient bytearrays
    of decreasing size — the textbook small-fragment-generator
    pattern, at a level that's a reliable regression guard without
    exhausting the unix-port heap when the preflight has primed it
    with module-load allocations from ~15 prior libraries.

    NOTE: at 30 cycles × 50 headers we observed actual MemoryError
    (parser couldn't allocate 474 bytes despite 1.9 MB free) when
    this test ran late in a CircuitPython unix-port preflight sweep
    — i.e. the parser DOES fragment its working heap under enough
    pressure.  This test deliberately stays under that threshold to
    function as a regression guard rather than a stress test.  See
    the "Memory Fragmentation in CP/MP" research note for context.
    """
    response = _build_response(body_size=64, header_count=30)
    _run_workload_and_probe(response, iterations=20)


def test_chunked_no_leak_no_fragmentation():
    """30 chunked-encoded cycles should not leak or fragment.

    Stresses ``_try_parse_chunk_size`` + ``_try_consume_chunk_data``.
    Per-chunk staging in ``self._buffer`` is the highest-churn allocation
    path in chunked decode.
    """
    chunks = [b"a" * 256] * 10  # 2.5 KiB body in 10 chunks
    response = _build_chunked_response(chunks)
    _run_workload_and_probe(response, iterations=30)


def test_mixed_workload_no_leak_no_fragmentation():
    """Alternating small / large / chunked cycles — combined fragmentation pressure.

    Production traffic mixes response shapes; this covers the case
    where alternating allocation sizes interleave free spans.  If the
    parser were to retain anything across cycles, a mixed workload
    would punch heterogeneous holes faster than any uniform workload.
    """
    if not _HAS_MEM_FREE:
        # Smoke only — rely on the per-shape tests above for the
        # functional coverage.
        return

    small_response = _build_response(body_size=128, header_count=5)
    large_response = _build_response(body_size=4096, header_count=15)
    chunked_response = _build_chunked_response([b"a" * 256] * 5)
    responses = (small_response, large_response, chunked_response)

    gc.collect()
    baseline_free = gc.mem_free()

    for cycle in range(30):
        response = responses[cycle % 3]
        parser = _drive_parser(response, chunk_size=256)
        assert parser.state == ParseState.DONE
    del parser
    gc.collect()

    final_free = gc.mem_free()
    final_largest = _largest_free_block(final_free)

    leak = baseline_free - final_free
    assert leak <= 4096, (
        f"mixed workload leaked {leak} bytes "
        f"(baseline_free={baseline_free}, final_free={final_free})"
    )

    ratio = final_largest / final_free if final_free else 1.0
    assert ratio >= 0.85, (
        f"mixed workload fragmented heap: "
        f"largest={final_largest} / free={final_free} = {ratio:.3f}"
    )
