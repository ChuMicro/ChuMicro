"""Wire-format tests for chumicro_requests — chunked transfer-encoding
decode in the streaming response parser (RFC 7230 §4.1).
"""

from chumicro_requests import (
    HttpOversizedError,
    ParseState,
    ResponseParser,
)

# ---------------------------------------------------------------------------
# ResponseParser chunked transfer-encoding
# ---------------------------------------------------------------------------


class TestResponseParserChunked:
    """RFC 7230 §4.1 chunked decode."""

    def _chunked_response(self, *chunks, status=200, extra_headers=()):
        """Build a chunked-encoded response from raw bytes chunks.

        Each *chunk* is the raw payload of one chunk; the helper
        builds the size lines + CRLFs + terminating zero-chunk.
        """
        parts = [
            f"HTTP/1.1 {status} OK\r\n".encode("ascii"),
            b"Transfer-Encoding: chunked\r\n",
            b"Content-Type: text/plain\r\n",
        ]
        for name, value in extra_headers:
            parts.append(f"{name}: {value}\r\n".encode("ascii"))
        parts.append(b"\r\n")
        for chunk in chunks:
            parts.append(f"{len(chunk):x}\r\n".encode("ascii"))
            parts.append(chunk)
            parts.append(b"\r\n")
        parts.append(b"0\r\n\r\n")  # last-chunk + empty trailer
        return b"".join(parts)

    def test_single_chunk(self):
        parser = ResponseParser()
        parser.feed(self._chunked_response(b"hello world"))
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello world"

    def test_multi_chunk_concatenates(self):
        parser = ResponseParser()
        parser.feed(self._chunked_response(b"Wiki", b"pedia ", b"in chunks."))
        assert parser.state == ParseState.DONE
        assert parser.body == b"Wikipedia in chunks."

    def test_empty_chunked_body(self):
        parser = ResponseParser()
        parser.feed(self._chunked_response())  # just `0\r\n\r\n`
        assert parser.state == ParseState.DONE
        assert parser.body == b""

    def test_chunked_split_across_feeds(self):
        full = self._chunked_response(b"hello", b"world")
        # Drip-feed one byte at a time — exercises the "buffer too short" return
        # paths in every state.
        parser = ResponseParser()
        for byte_index in range(len(full)):
            parser.feed(full[byte_index:byte_index + 1])
        assert parser.state == ParseState.DONE
        assert parser.body == b"helloworld"

    def test_chunk_extension_ignored(self):
        """A `;name=value` extension on the chunk-size line is silently dropped."""
        parser = ResponseParser()
        # Chunk size 5 with extension `;myext=foo`, then data, then 0
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5;myext=foo\r\n"
            b"hello\r\n"
            b"0\r\n\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"

    def test_trailer_headers_discarded(self):
        """Trailer headers between last-chunk and empty CRLF are accepted + ignored."""
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhello\r\n"
            b"0\r\n"
            b"X-Trailer: extra-info\r\n"
            b"X-Other: more-info\r\n"
            b"\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"

    def test_transfer_encoding_takes_precedence_over_content_length(self):
        """Per RFC 7230 §3.3.3, when both are present, chunked wins."""
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Content-Length: 999\r\n"  # ignored
            b"\r\n"
            b"5\r\nhello\r\n"
            b"0\r\n\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"

    def test_unsupported_transfer_encoding_fails(self):
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: gzip\r\n"
            b"\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.ERROR
        assert "gzip" in str(parser.error)

    def test_non_hex_chunk_size_fails(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"NOT-HEX\r\n",
        )
        assert parser.state == ParseState.ERROR
        assert "non-hex" in str(parser.error)

    def test_empty_chunk_size_line_fails(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"\r\n",
        )
        assert parser.state == ParseState.ERROR

    def test_missing_crlf_after_chunk_data_fails(self):
        parser = ResponseParser()
        # Chunk size 5, then 5 bytes, then "XX" instead of CRLF
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhelloXX0\r\n\r\n",
        )
        assert parser.state == ParseState.ERROR
        assert "CRLF after chunk" in str(parser.error)

    def test_chunked_oversized_fails(self):
        parser = ResponseParser(max_body_bytes=10)
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"100\r\n",  # 256 bytes > cap of 10
        )
        assert parser.state == ParseState.ERROR
        assert isinstance(parser.error, HttpOversizedError)

    def test_chunked_eof_mid_data_fails(self):
        parser = ResponseParser()
        parser.feed(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"100\r\nshort",  # claims 256 bytes, only 5 sent
        )
        assert parser.state == ParseState.CHUNK_DATA
        parser.feed_eof()
        assert parser.state == ParseState.ERROR
        assert "mid-chunked-body" in str(parser.error)

    def test_transfer_encoding_with_whitespace(self):
        """`chunked` may have surrounding whitespace per RFC 7230 §3.2."""
        parser = ResponseParser()
        body_bytes = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding:   chunked  \r\n"  # leading/trailing space
            b"\r\n"
            b"5\r\nhello\r\n0\r\n\r\n"
        )
        parser.feed(body_bytes)
        assert parser.state == ParseState.DONE
        assert parser.body == b"hello"
