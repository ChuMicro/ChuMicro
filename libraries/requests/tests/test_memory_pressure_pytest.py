"""Host-side memory-pressure regression tests for the response parser.

These tests run on CPython using :mod:`tracemalloc` to profile per-
operation allocations and :mod:`gc` to force a clean baseline before
each measurement.  They catch Python-level leaks in
:class:`ResponseParser` — accumulating list/dict references,
buffer growth that doesn't release across cycles, retained closures.

These don't replicate device-level heap fragmentation: CP / MP
allocators differ from CPython.  Device-side soak measurement is a
separate concern from this unit suite.

Why the library itself never calls ``gc.collect()``: fragmentation is
prevented by design (parser tears down per-request, no module-level
or per-instance accumulation, bounded body cap) and host-side leaks
are caught here.  A
library calling ``gc.collect()`` invisibly inside ``handle()`` would
impose its collect cadence on every other task in the system; the
runner contract (``handle`` returns quickly) keeps that decision in
the user's hands.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import tracemalloc

from chumicro_requests import ParseState, ResponseParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_response(*, body_size: int, header_count: int = 5) -> bytes:
    """Build a Content-Length response with *header_count* extra headers."""
    parts = [b"HTTP/1.1 200 OK\r\n"]
    for index in range(header_count):
        parts.append(f"X-Custom-{index}: value-{index}\r\n".encode())
    parts.append(f"Content-Length: {body_size}\r\n".encode())
    parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
    parts.append(b"x" * body_size)
    return b"".join(parts)


def _build_chunked_response(chunks: list) -> bytes:
    """Build a chunked-encoded response carrying *chunks* (list of bytes)."""
    parts = [b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"]
    for chunk in chunks:
        parts.append(f"{len(chunk):x}\r\n".encode())
        parts.append(chunk)
        parts.append(b"\r\n")
    parts.append(b"0\r\n\r\n")
    return b"".join(parts)


def _drive_parser(response_bytes: bytes, *, chunk_size: int = 512) -> ResponseParser:
    """Run a fresh parser to ``DONE`` over *response_bytes* fed in chunks."""
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


def _measure_growth(operation, *, warmup_iterations=50, sample_iterations=300):
    """Run *operation* warmup + sample times, returning post-GC heap growth.

    Returns ``(growth_bytes, current_kib, peak_kib)``.  A clean
    implementation should produce growth_bytes near zero.
    """
    gc.collect()
    tracemalloc.start()
    try:
        for _ in range(warmup_iterations):
            operation()
        gc.collect()
        baseline_current, _baseline_peak = tracemalloc.get_traced_memory()

        for _ in range(sample_iterations):
            operation()
        gc.collect()
        final_current, final_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    growth = final_current - baseline_current
    return growth, final_current / 1024, final_peak / 1024


# ---------------------------------------------------------------------------
# Small Content-Length responses — the typical sensor-API path
# ---------------------------------------------------------------------------


class TestResponseParserSmallBodyNoLeak:
    def test_small_body_no_growth(self) -> None:
        """300 small Content-Length responses should not accumulate heap.

        Detects: parser-internal bytearray growth across cycles,
        CaseInsensitiveDict entries retained between parsers, lingering
        references to status/reason strings.
        """
        response = _build_response(body_size=128, header_count=5)

        def operation() -> None:
            parser = _drive_parser(response, chunk_size=512)
            assert parser.state == ParseState.DONE
            assert parser.body == b"x" * 128

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=50, sample_iterations=300,
        )
        assert growth_bytes < 4096, (
            f"small-body parser leaked {growth_bytes} bytes over 300 iterations"
        )


# ---------------------------------------------------------------------------
# Large Content-Length responses — exercises body bytearray.extend path
# ---------------------------------------------------------------------------


class TestResponseParserLargeBodyNoLeak:
    def test_large_body_no_growth(self) -> None:
        """200 8 KiB-body responses should not leak across cycles.

        Stresses ``_absorb_body_bytes`` and the Content-Length body
        accumulation path; each parser allocates and frees an 8 KiB
        bytearray.  Growth here would imply parsers themselves are
        being retained.
        """
        response = _build_response(body_size=8192, header_count=10)

        def operation() -> None:
            parser = _drive_parser(response, chunk_size=512)
            assert parser.state == ParseState.DONE

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=20, sample_iterations=200,
        )
        assert growth_bytes < 4096, (
            f"large-body parser leaked {growth_bytes} bytes over 200 iterations"
        )


# ---------------------------------------------------------------------------
# Many headers — exercises the read-cursor + periodic compaction
# in _try_parse_headers
# ---------------------------------------------------------------------------


class TestResponseParserManyHeadersNoLeak:
    def test_many_headers_no_growth(self) -> None:
        """50-header responses should not accumulate heap across 200 cycles.

        Many-header responses drive the parser's read-cursor +
        periodic compaction path hard: each header line advances
        ``ResponseParser._read_offset`` and, once half the staging
        buffer is consumed, triggers the in-place
        ``self._buffer[:offset] = b""`` compaction.  Guards against
        any retained reference into the staging buffer across that
        repeated consume/compact cycle.
        """
        response = _build_response(body_size=64, header_count=50)

        def operation() -> None:
            parser = _drive_parser(response, chunk_size=128)
            assert parser.state == ParseState.DONE
            assert len(parser.headers) >= 50

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=20, sample_iterations=200,
        )
        assert growth_bytes < 4096, (
            f"many-headers parser leaked {growth_bytes} bytes over 200 iterations"
        )


# ---------------------------------------------------------------------------
# Chunked transfer encoding — exercises per-chunk decode + body assembly
# ---------------------------------------------------------------------------


class TestResponseParserChunkedNoLeak:
    def test_chunked_no_growth(self) -> None:
        """Chunked responses should not leak across cycles.

        The chunked decode path (``_try_consume_chunk_data`` /
        ``_try_parse_chunk_size``) drains bytes from the staging
        buffer one chunk at a time.  Repeated cycles must not retain
        across parsers.
        """
        chunks = [b"a" * 256] * 10  # 2.5 KiB body in 10 chunks
        response = _build_chunked_response(chunks)

        def operation() -> None:
            parser = _drive_parser(response, chunk_size=128)
            assert parser.state == ParseState.DONE
            assert parser.body == b"a" * 2560

        growth_bytes, _current_kib, _peak_kib = _measure_growth(
            operation, warmup_iterations=20, sample_iterations=200,
        )
        assert growth_bytes < 4096, (
            f"chunked parser leaked {growth_bytes} bytes over 200 iterations"
        )


# ---------------------------------------------------------------------------
# Single long-lived parser — buffer reuse / state reset coverage
# ---------------------------------------------------------------------------


class TestResponseParserBuffersReleaseAfterDone:
    def test_internal_buffer_releases_after_done(self) -> None:
        """After ``state == DONE`` the staging buffer should have shed its bytes.

        The parser's ``_buffer`` is consumed as headers parse; once the
        body state is entered, body bytes flow straight to ``_body``
        without restaging.  At ``DONE`` the staging buffer should hold
        no payload — only at most a few trailing bytes from the final
        chunked decode.  Regression guard for any future change that
        retains the full staging buffer past completion.
        """
        response = _build_response(body_size=4096, header_count=10)
        parser = _drive_parser(response, chunk_size=512)
        assert parser.state == ParseState.DONE
        # Staging buffer is internal but observable; once DONE it
        # should not still be carrying the full body.
        assert len(parser._buffer) < 64, (
            f"staging buffer unexpectedly retained {len(parser._buffer)} bytes after DONE"
        )
