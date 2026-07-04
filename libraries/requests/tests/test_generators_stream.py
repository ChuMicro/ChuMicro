"""Streamed-body generator surface — ``stream`` + ``BodyReader``.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Drives the generators directly with
``gen.send`` against a scripted ``FakeSocket``, the same way the fetch
suites do.
"""

from _generator_helpers import _drive
from chumicro_requests._wire import HttpError, HttpTimeoutError
from chumicro_requests.generators import fetch, stream
from chumicro_requests.testing import canned_response, make_factory
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks


def _chunked_response(*chunks):
    """Build a chunked-encoded response from raw payload chunks."""
    parts = [
        b"HTTP/1.1 200 OK\r\n",
        b"Transfer-Encoding: chunked\r\n",
        b"\r\n",
    ]
    for chunk in chunks:
        parts.append(f"{len(chunk):x}\r\n".encode("ascii"))
        parts.append(chunk)
        parts.append(b"\r\n")
    parts.append(b"0\r\n\r\n")
    return b"".join(parts)


def test_stream_reads_chunked_body_through_caller_buffer():
    sock = FakeSocket()
    sock.enqueue_recv(_chunked_response(b"alpha", b"beta", b"gamma"))
    ticks = FakeTicks()

    def app():
        reader = yield from stream(
            make_factory(sock), "GET", "http://example.test/", ticks=ticks,
        )
        scratch = bytearray(4)
        view = memoryview(scratch)
        collected = bytearray()
        while True:
            count = yield from reader.read_into(view)
            if count == 0:
                break
            collected.extend(view[:count])
        return reader.response.status_code, bytes(collected)

    status_code, body = _drive(app(), ticks)
    assert status_code == 200
    assert body == b"alphabetagamma"
    assert sock.closed is True


def test_stream_returns_reader_before_body_completes():
    """stream() hands back the reader at headers-complete: the response
    status is readable while unread body bytes are still queued on the
    socket."""
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"z" * 1500))
    ticks = FakeTicks()

    def app():
        reader = yield from stream(
            make_factory(sock), "GET", "http://example.test/", ticks=ticks,
            stream_buffer_size=64,
        )
        return reader

    reader = _drive(app(), ticks)
    assert reader.response.status_code == 200
    assert reader.response.streamed is True


def test_stream_raises_timeout_before_headers():
    sock = FakeSocket()  # nothing enqueued -> recv_into always EAGAIN
    ticks = FakeTicks()

    def app():
        reader = yield from stream(
            make_factory(sock), "GET", "http://example.test/",
            ticks=ticks, timeout_ms=5,
        )
        return reader

    with raises(HttpTimeoutError):
        _drive(app(), ticks, advance_ms=1, max_steps=100)


def test_reader_cancel_closes_socket_and_read_raises():
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"w" * 2000))
    ticks = FakeTicks()

    def app():
        reader = yield from stream(
            make_factory(sock), "GET", "http://example.test/", ticks=ticks,
            stream_buffer_size=64,
        )
        scratch = bytearray(16)
        count = yield from reader.read_into(memoryview(scratch))
        reader.cancel()
        try:
            yield from reader.read_into(memoryview(scratch))
        except HttpError as error:
            return count, str(error)
        return count, None

    first_count, error_message = _drive(app(), ticks)
    assert first_count > 0
    assert error_message is not None
    assert "cancelled" in error_message
    assert sock.closed is True


def test_closing_a_suspended_stream_generator_closes_the_socket():
    """GeneratorExit mid-transfer (a cancelled runner task) closes the
    request's socket instead of leaking it until the timeout."""
    sock = FakeSocket()
    sock.enqueue_recv(canned_response(body=b"k" * 2000))
    ticks = FakeTicks()

    def app():
        reader = yield from stream(
            make_factory(sock), "GET", "http://example.test/", ticks=ticks,
            stream_buffer_size=64,
        )
        scratch = bytearray(8)
        while True:
            count = yield from reader.read_into(memoryview(scratch))
            if count == 0:
                return None

    gen = app()
    gen.send(None)
    for _ in range(5):
        ticks.advance(1)
        gen.send(ticks.ticks_ms())
    gen.close()
    assert sock.closed is True


def test_closing_stream_generator_before_headers_closes_the_socket():
    """GeneratorExit while stream() is still waiting for headers closes
    the request's socket via the same cancel path."""
    sock = FakeSocket()  # nothing enqueued -> parked awaiting headers
    ticks = FakeTicks()

    def app():
        reader = yield from stream(
            make_factory(sock), "GET", "http://example.test/", ticks=ticks,
        )
        return reader

    gen = app()
    gen.send(None)
    for _ in range(3):
        ticks.advance(1)
        gen.send(ticks.ticks_ms())
    gen.close()
    assert sock.closed is True


def test_closing_a_suspended_fetch_generator_closes_the_socket():
    sock = FakeSocket()  # nothing enqueued -> fetch parks in RECEIVING
    ticks = FakeTicks()
    gen = fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks)
    gen.send(None)
    for _ in range(3):
        ticks.advance(1)
        gen.send(ticks.ticks_ms())
    gen.close()
    assert sock.closed is True
