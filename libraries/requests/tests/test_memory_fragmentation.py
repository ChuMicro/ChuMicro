"""Cross-runtime heap-fragmentation regression tests for ResponseParser.

Runs on every runtime via the chumicro test harness (MicroPython /
CircuitPython unix-port) and via pytest (CPython).  Heap-state
assertions only fire on runtimes that expose ``gc.mem_free`` —
i.e. MP and CP — because this is a property of those allocators,
not of CPython's pymalloc.

Methodology — delta-based assertions on baseline-after-setup
-----------------------------------------------------------

Captures the heap baseline AFTER the test's fixture setup but
BEFORE the workload loop.  The assertions then measure ONLY what
the workload itself contributes — bytes consumed and bytes of
new fragmentation holes added — independent of whatever heap
state the test inherited from the harness.

This matters because the unix-port test harness runs all
libraries' tests in a single process: prior libraries' test
imports leave permanent allocations in ``sys.modules`` (test
data, canned bytes literals, test functions), and that residue
fragments the heap before any test runs.  An assertion like
``final_largest / final_free ≥ 0.85`` would be dominated by that
inherited fragmentation, not by anything the workload did.
Probe data confirmed: a fresh-process unix-port heap has
baseline ratio 0.9559; after the requests test files are
imported (no tests run), the ratio drops to 0.8463; and the
parser workload itself adds **0 bytes** of holes on top of
either baseline.

This pattern is unique to the test harness — on a real board
modules are frozen in flash (not heap), test files don't ship,
and there are no test fixtures.  See ``plans/next-up.md``
§"Heap-fragmentation test methodology" for the investigation.

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
# Largest-contiguous-block probe
# ---------------------------------------------------------------------------


def _largest_free_block(upper_hint):
    """Return the largest currently-allocatable bytearray size in bytes.

    Bisects between 0 and *upper_hint* (typically ``gc.mem_free``).
    Each successful sub-allocation is followed by ``gc.collect()``
    because MP/CP don't refcount — without the per-iteration collect
    each successful probe would permanently consume the space it
    just measured and the bisect would converge on free / 2.
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
            gc.collect()
            low = mid + 1
    return best


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
                          fragmentation_tolerance=4096):
    """Assert *workload* contributes ≤ tolerance bytes consumed + fragmented.

    Baseline captured *after* the test's fixture setup, so the delta
    reflects only the workload itself — not whatever the test
    environment had already allocated.  See module docstring for
    the methodology rationale.

    On CPython (no ``mem_free``) the workload still runs as a
    smoke check but no heap assertions fire.
    """
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
    fix is subprocess-per-file isolation in the harness (see
    ``plans/next-up.md`` §"Heap-fragmentation test methodology"),
    not dialing the workload down.
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
