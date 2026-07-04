"""Streamed-response framing primitives: the chunk-size writer, the
``_StreamState`` framing machine, ``build_streaming_response``, and
``encode_streaming_headers``.

Server-side mirror of ``chumicro_requests``'s streamed-body tests — here
the framing runs *out* to a socket, so these exercise the framing bytes
and the source-contract conventions directly; ``test_http_streaming_e2e.py``
drives them end to end through a FakeSocket.
"""

from chumicro_http_server import (
    CaseInsensitiveDict,
    ServerError,
    ServerProtocolError,
)
from chumicro_http_server.streaming import (
    SOURCE_EOF,
    StreamingResponse,
    _hex_len,
    _StreamState,
    _write_chunk_header,
    build_streaming_response,
    encode_streaming_headers,
)
from chumicro_test_harness.assertions import raises


def _list_source(chunks):
    """A source that hands out *chunks* in order, then :data:`SOURCE_EOF`.

    The five-line shape a sensor-log generator uses — each chunk must
    fit the buffer it's handed.
    """
    iterator = iter(chunks)

    def source(buffer):
        try:
            data = next(iterator)
        except StopIteration:
            return SOURCE_EOF
        count = len(data)
        buffer[:count] = data
        return count

    return source


def _drain(stream, *, budget=1_000_000, ticks=1000):
    """Pump *stream* like the connection would and return the wire bytes.

    Sends at most *budget* bytes per simulated tick (default effectively
    unbounded) into a bytearray, driving to completion or *ticks*.
    """
    wire = bytearray()
    for _ in range(ticks):
        consumed = 0
        while consumed < budget:
            if stream.pending:
                start = stream.out_pos
                room = budget - consumed
                available = stream.out_end - start
                stop = start + (available if available <= room else room)
                wire += bytes(stream.out_view[start:stop])
                sent = stop - start
                stream.advance_sent(sent)
                consumed += sent
                continue
            if stream.finished:
                return bytes(wire)
            if not stream.pull():
                break  # dry this tick
    return bytes(wire)


def _dechunk(body):
    """Decode a chunked body back to its payload (test-side reference)."""
    out = bytearray()
    index = 0
    while True:
        crlf = body.index(b"\r\n", index)
        size = int(body[index:crlf], 16)
        index = crlf + 2
        if size == 0:
            break
        out += body[index:index + size]
        index += size + 2
    return bytes(out)


class TestHexLen:
    def test_single_digit(self):
        assert _hex_len(0) == 1
        assert _hex_len(15) == 1

    def test_boundaries(self):
        assert _hex_len(16) == 2
        assert _hex_len(255) == 2
        assert _hex_len(256) == 3
        assert _hex_len(1024) == 3
        assert _hex_len(0x10000) == 5


class TestWriteChunkHeader:
    """The chunk-size line is written straight into the staging buffer —
    no allocation per chunk beyond the reused buffer."""

    def test_writes_hex_size_and_crlf_ending_at_end(self):
        buffer = bytearray(16)
        # 0x2ab = 683; header "2ab\r\n" is 5 bytes ending at index 8.
        header_len = _write_chunk_header(buffer, 8, 0x2AB)
        assert header_len == 5
        assert bytes(buffer[8 - header_len:8]) == b"2ab\r\n"

    def test_single_digit_size(self):
        buffer = bytearray(8)
        header_len = _write_chunk_header(buffer, 5, 6)
        assert header_len == 3
        assert bytes(buffer[5 - header_len:5]) == b"6\r\n"

    def test_lowercase_hex(self):
        buffer = bytearray(16)
        header_len = _write_chunk_header(buffer, 10, 0xFF)
        assert bytes(buffer[10 - header_len:10]) == b"ff\r\n"


class TestBuildStreamingResponse:
    def test_defaults_to_200_chunked(self):
        response = build_streaming_response(source=_list_source([b"x"]))
        assert isinstance(response, StreamingResponse)
        assert response.status_code == 200
        assert response.reason == "OK"
        assert response.content_length is None  # chunked

    def test_content_length_framing(self):
        response = build_streaming_response(
            source=_list_source([b"x" * 10]), content_length=10,
        )
        assert response.content_length == 10

    def test_status_reason_lookup(self):
        assert build_streaming_response(206, source=_list_source([])).reason == "Unknown"
        assert build_streaming_response(200, source=_list_source([])).reason == "OK"

    def test_headers_merged_into_case_insensitive_dict(self):
        response = build_streaming_response(
            source=_list_source([]), headers={"X-Trace": "abc"},
        )
        assert isinstance(response.headers, CaseInsensitiveDict)
        assert response.headers["x-trace"] == "abc"

    def test_repr_shows_framing(self):
        assert "chunked" in repr(build_streaming_response(source=_list_source([])))
        assert "content-length=7" in repr(
            build_streaming_response(source=_list_source([]), content_length=7),
        )


class TestEncodeStreamingHeaders:
    def test_chunked_when_no_length(self):
        response = build_streaming_response(source=_list_source([]))
        wire = encode_streaming_headers(response)
        assert wire.startswith(b"HTTP/1.1 200 OK\r\n")
        assert b"Transfer-Encoding: chunked\r\n" in wire
        assert b"Content-Length:" not in wire
        assert b"Connection: close\r\n" in wire
        assert wire.endswith(b"\r\n\r\n")

    def test_content_length_when_length_known(self):
        response = build_streaming_response(source=_list_source([]), content_length=4096)
        wire = encode_streaming_headers(response)
        assert b"Content-Length: 4096\r\n" in wire
        assert b"Transfer-Encoding:" not in wire

    def test_custom_headers_emitted(self):
        response = build_streaming_response(
            source=_list_source([]), headers=[("Content-Type", "text/csv")],
        )
        wire = encode_streaming_headers(response)
        assert b"Content-Type: text/csv\r\n" in wire

    def test_rejects_control_chars_in_header(self):
        response = build_streaming_response(
            source=_list_source([]), headers=[("X-Echo", "a\r\nX-Injected: 1")],
        )
        with raises(ServerProtocolError):
            encode_streaming_headers(response)

    def test_rejects_control_chars_in_reason(self):
        response = build_streaming_response(source=_list_source([]))
        response.reason = "OK\r\nX-Injected: 1"
        with raises(ServerProtocolError):
            encode_streaming_headers(response)


class TestStreamStateChunkedFraming:
    def test_single_fill_framed_as_one_chunk(self):
        stream = _StreamState(_list_source([b"hello"]), None, bytearray(64))
        assert _dechunk(_drain(stream)) == b"hello"

    def test_multiple_fills_frame_multiple_chunks(self):
        stream = _StreamState(
            _list_source([b"aa", b"bbb", b"c"]), None, bytearray(64),
        )
        wire = _drain(stream)
        assert wire == b"2\r\naa\r\n3\r\nbbb\r\n1\r\nc\r\n0\r\n\r\n"

    def test_empty_body_is_just_the_terminator(self):
        stream = _StreamState(_list_source([]), None, bytearray(64))
        assert _drain(stream) == b"0\r\n\r\n"

    def test_fill_at_capacity(self):
        # Fill the whole usable window in one chunk — exercises the
        # header-reserve sizing at the boundary.
        buffer = bytearray(64)
        capacity = _StreamState(_list_source([]), None, bytearray(64))._fill_capacity  # noqa: SLF001
        payload = b"z" * capacity
        stream = _StreamState(_list_source([payload]), None, buffer)
        assert _dechunk(_drain(stream)) == payload


class TestStreamStateContentLengthFraming:
    def test_body_framed_raw(self):
        stream = _StreamState(_list_source([b"abc", b"def"]), 6, bytearray(64))
        assert _drain(stream) == b"abcdef"

    def test_short_body_before_eof_raises(self):
        # Source signals EOF after fewer bytes than the declared length —
        # framing is now inconsistent, so the drain raises a ServerError
        # (the connection layer turns this into a close).
        stream = _StreamState(_list_source([b"abc"]), 6, bytearray(64))
        with raises(ServerError):
            _drain(stream)

    def test_overshoot_raises(self):
        # A fill that would carry the total past the declared length.
        stream = _StreamState(_list_source([b"abcd", b"efgh"]), 6, bytearray(64))
        with raises(ServerError):
            _drain(stream)


class TestStreamStateSourceContract:
    def test_dry_return_is_not_progress(self):
        # 0 means "no bytes this tick", distinct from EOF: pull() reports
        # no progress and the body is not finished.
        stream = _StreamState(lambda _buffer: 0, None, bytearray(64))
        assert stream.pull() is False
        assert stream.finished is False

    def test_eof_return_finishes(self):
        stream = _StreamState(lambda _buffer: SOURCE_EOF, 0, bytearray(64))
        assert stream.pull() is True
        assert stream.finished is True

    def test_out_of_range_return_raises(self):
        stream = _StreamState(lambda buffer: len(buffer) + 1, None, bytearray(64))
        with raises(ServerError):
            stream.pull()

    def test_tiny_buffer_rejected_for_chunked(self):
        # A window too small to hold a chunk header + one payload byte +
        # trailing CRLF is a construction error, not a silent 0-capacity.
        with raises(ValueError):
            _StreamState(_list_source([]), None, bytearray(4))

    def test_body_bytes_sent_counts_payload_only(self):
        stream = _StreamState(_list_source([b"aa", b"bbb"]), None, bytearray(64))
        _drain(stream)
        assert stream.body_bytes_sent == 5
