"""requests client: ``stream=True`` — chunked and length-unknown framing,
plus a slow-trickle peer delivering bytes one at a time across ticks.
"""

from chumicro_requests import HttpProtocolError
from chumicro_requests.testing import make_client
from chumicro_sockets.testing import FakeSocket


def _chunked_response(*chunks, status=200):
    """Build a chunked-encoded response from raw payload chunks."""
    parts = [
        f"HTTP/1.1 {status} OK\r\n".encode("ascii"),
        b"Transfer-Encoding: chunked\r\n",
        b"Content-Type: application/octet-stream\r\n",
        b"\r\n",
    ]
    for chunk in chunks:
        parts.append(f"{len(chunk):x}\r\n".encode("ascii"))
        parts.append(chunk)
        parts.append(b"\r\n")
    parts.append(b"0\r\n\r\n")
    return b"".join(parts)


def _stream_until_done(client, handle, ticks, *, read_size=32, max_ticks=4000):
    """Drive *client* and drain *handle* per tick; return the body bytes."""
    collected = bytearray()
    scratch = bytearray(read_size)
    view = memoryview(scratch)
    for _ in range(max_ticks):
        if client.check(ticks.ticks_ms()):
            client.handle(ticks.ticks_ms())
        count = handle.read_body_into(view)
        if count:
            collected.extend(view[:count])
        elif handle.done:
            return bytes(collected)
        ticks.advance(1)
    raise AssertionError(f"stream never completed within {max_ticks} ticks")


class _TrickleSocket(FakeSocket):
    """FakeSocket that hands out one byte per recv, EAGAIN every other call.

    Models a slow peer: each tick's recv loop gets at most one byte and
    every second recv attempt reports "nothing yet", so the exchange is
    forced to span many ticks.
    """

    def __init__(self):
        super().__init__()
        self._starve_next_recv = False

    def recv_into(self, buffer, nbytes=0):
        if self._starve_next_recv:
            self._starve_next_recv = False
            self.enqueue_eagain_for_recv(1)
        else:
            self._starve_next_recv = True
        capacity = nbytes if nbytes > 0 else len(buffer)
        return super().recv_into(buffer, min(capacity, 1))


class TestStreamChunked:
    """Chunked bodies stream chunk by chunk through the staging window."""

    def test_multi_chunk_body_reassembles(self):
        body_chunks = (b"alpha-", b"beta-", b"gamma-", b"delta")
        socket = FakeSocket()
        socket.enqueue_recv(_chunked_response(*body_chunks))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", stream=True)
        collected = _stream_until_done(client, handle, ticks)
        assert collected == b"".join(body_chunks)
        assert handle.result.streamed is True

    def test_chunked_body_over_cap_streams(self):
        chunks = tuple(bytes([65 + index]) * 200 for index in range(6))  # 1200 B
        socket = FakeSocket()
        socket.enqueue_recv(_chunked_response(*chunks))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=100,
            stream_buffer_size=64,
        )
        handle = client.get("http://example.test/", stream=True)
        collected = _stream_until_done(client, handle, ticks)
        assert collected == b"".join(chunks)
        assert handle.error is None

    def test_chunked_peer_close_mid_body_fails_the_stream(self):
        socket = FakeSocket()
        # Chunk header claims 0x100 bytes; only 5 arrive before the FIN.
        socket.enqueue_recv(
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"100\r\nshort",
        )
        socket.simulate_peer_close()
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", stream=True)
        scratch = bytearray(32)
        for _ in range(100):
            if handle.done:
                break
            client.handle(ticks.ticks_ms())
            handle.read_body_into(scratch)
            ticks.advance(1)
        assert handle.done is True
        assert isinstance(handle.error, HttpProtocolError)
        # The response had already published (headers were valid), so the
        # partial delivery is detectable via handle.error.
        assert handle.response is not None


class TestStreamLengthUnknown:
    """No Content-Length, no chunking: stream until the peer closes."""

    def test_read_until_close_streams(self):
        body = b"n" * 700
        socket = FakeSocket()
        socket.enqueue_recv(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n" + body,
        )
        socket.simulate_peer_close()
        client, ticks, _ = make_client(
            socket_or_factory=socket, stream_buffer_size=128,
        )
        handle = client.get("http://example.test/", stream=True)
        collected = _stream_until_done(client, handle, ticks)
        assert collected == body
        assert handle.error is None


class TestStreamSlowTrickle:
    """One byte per recv with EAGAIN interleave: progress spans many ticks."""

    def test_chunked_trickle_across_ticks(self):
        body_chunks = (b"drip", b"feed", b"body")
        socket = _TrickleSocket()
        socket.enqueue_recv(_chunked_response(*body_chunks))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get(
            "http://example.test/", stream=True, timeout_ms=60_000,
        )
        ticks_used = 0
        collected = bytearray()
        scratch = bytearray(4)
        view = memoryview(scratch)
        for _ in range(4000):
            ticks_used += 1
            if client.check(ticks.ticks_ms()):
                client.handle(ticks.ticks_ms())
            count = handle.read_body_into(view)
            if count:
                collected.extend(view[:count])
            elif handle.done:
                break
            ticks.advance(1)
        assert handle.done is True
        assert bytes(collected) == b"".join(body_chunks)
        # A trickled exchange genuinely spans ticks (the wire is ~90
        # bytes at one byte per tick-with-EAGAIN-gaps).
        assert ticks_used > 50
