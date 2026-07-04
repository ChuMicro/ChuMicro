"""Streamed response bodies end to end: content-length + chunked framing
over a FakeSocket, EAGAIN mid-body, per-tick fairness across two
connections, stalled-client timeout, handler-raises-mid-stream, and the
source EOF/dry conventions.

The handler pushes a body far larger than the heap through a fixed
staging window, and the server drains it to the client across ticks
under the same per-tick send budget and EAGAIN backpressure as a
buffered response.
"""

import errno

from chumicro_http_server import (
    HttpServer,
    build_response,
)
from chumicro_http_server.streaming import (
    SOURCE_EOF,
    build_streaming_response,
)
from chumicro_http_server.testing import FakeListener, request_bytes
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def _make_server(*, sockets, handler, **kwargs):
    ticks = FakeTicks()

    def transport_factory():
        return FakeListener(sockets)

    server = HttpServer(
        transport_factory=transport_factory,
        handler=handler,
        ticks=ticks,
        **kwargs,
    )
    return server, ticks


def _drive_until_idle(server, ticks, *, max_ticks=2000):
    for _ in range(max_ticks):
        server.handle(ticks.ticks_ms())
        if server.in_flight == 0:
            return
        ticks.advance(1)
    raise AssertionError(f"server still busy after {max_ticks} ticks")


def _connection(raw):
    socket = FakeSocket()
    socket.enqueue_recv(raw)
    return socket, ("127.0.0.1", 12345)


def _list_source(chunks):
    """Hand out *chunks* in order, then :data:`SOURCE_EOF`."""
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


def _fixed_source(total, per_fill, *, mark=b"x"):
    """Produce *total* bytes of *mark*, at most *per_fill*/window per tick."""
    produced = [0]

    def source(buffer):
        if produced[0] >= total:
            return SOURCE_EOF
        count = min(per_fill, total - produced[0], len(buffer))
        buffer[:count] = mark * count
        produced[0] += count
        return count

    return source


def _split_wire(sent):
    """Return ``(headers, body)`` split on the header terminator."""
    head, _, body = bytes(sent).partition(b"\r\n\r\n")
    return head, body


def _dechunk(body):
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


class TestContentLengthStreaming:
    def test_wire_headers_and_body(self):
        payload = b"sensor-log-line\n" * 40  # 640 bytes
        sock, peer = _connection(request_bytes(path="/dump"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(
                200, source=_list_source([payload[i:i + 64] for i in range(0, len(payload), 64)]),
                content_length=len(payload),
            ),
        )
        _drive_until_idle(server, ticks)
        head, body = _split_wire(sock.sent)
        assert head.startswith(b"HTTP/1.1 200 OK")
        assert b"Content-Length: 640" in head
        assert b"Transfer-Encoding" not in head
        assert b"Connection: close" in head
        assert body == payload
        assert sock.closed is True

    def test_body_larger_than_window_drains_in_many_fills(self):
        # Body many times the staging window, through a small window —
        # never materialized whole; proves the window bounds RAM, not the
        # body.  Kept modest so the test itself fits the tight CP heap
        # lane (the server side never holds more than one window).
        total = 1024
        sock, peer = _connection(request_bytes(path="/big"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(
                200, source=_fixed_source(total, 100), content_length=total,
            ),
            stream_buffer_size=128,
        )
        _drive_until_idle(server, ticks)
        _head, body = _split_wire(sock.sent)
        assert body == b"x" * total


class TestChunkedStreaming:
    def test_wire_headers_and_chunk_framing(self):
        sock, peer = _connection(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(
                200, source=_list_source([b"alpha", b"beta", b"gamma"]),
            ),
        )
        _drive_until_idle(server, ticks)
        head, body = _split_wire(sock.sent)
        assert b"Transfer-Encoding: chunked" in head
        assert b"Content-Length" not in head
        assert body == b"5\r\nalpha\r\n4\r\nbeta\r\n5\r\ngamma\r\n0\r\n\r\n"
        assert _dechunk(body) == b"alphabetagamma"

    def test_empty_chunked_body_is_terminator_only(self):
        sock, peer = _connection(request_bytes(path="/empty"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(200, source=_list_source([])),
        )
        _drive_until_idle(server, ticks)
        _head, body = _split_wire(sock.sent)
        assert body == b"0\r\n\r\n"

    def test_large_chunked_body_reassembles(self):
        total = 1500
        sock, peer = _connection(request_bytes(path="/big"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(200, source=_fixed_source(total, 300)),
            stream_buffer_size=128,
        )
        _drive_until_idle(server, ticks)
        _head, body = _split_wire(sock.sent)
        assert _dechunk(body) == b"x" * total
        assert body.endswith(b"0\r\n\r\n")


class _EagainOnBodySends(FakeSocket):
    """FakeSocket that EAGAINs specific send() calls, counting from 1.

    Lets a test EAGAIN the *body* sends (call 2+, after the one header
    send) rather than the header send that ``enqueue_eagain_for_send``
    would hit first.
    """

    def __init__(self, eagain_on):
        super().__init__()
        self._send_count = 0
        self._eagain_on = set(eagain_on)

    def send(self, data):
        self._send_count += 1
        if self._send_count in self._eagain_on:
            raise OSError(errno.EAGAIN, "would block")
        return super().send(data)


class TestStreamingBackpressure:
    def test_send_eagain_mid_body_resumes(self):
        # EAGAIN the 2nd + 4th send() calls — the header block goes out on
        # call 1, so these land squarely on the body drain, exercising the
        # streamed-send EAGAIN backpressure (not the header path's).
        sock = _EagainOnBodySends(eagain_on={2, 4})
        sock.enqueue_recv(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, ("127.0.0.1", 1))],
            handler=lambda request: build_streaming_response(
                200, source=_fixed_source(600, 100), content_length=600,
            ),
            send_budget_per_tick=120,
        )
        _drive_until_idle(server, ticks)
        _head, body = _split_wire(sock.sent)
        assert body == b"x" * 600

    def test_non_eagain_socket_error_mid_body_closes(self):
        # A non-EAGAIN socket error on a body send (peer reset) tears the
        # connection down rather than looping.
        class _FailOnBodySend(FakeSocket):
            def send(self, data):
                if self.sent:  # headers already went out — fail a body send
                    # Raw errno (not EAGAIN) — ``errno.EPIPE`` is absent on
                    # MicroPython; the connection layer only checks it isn't
                    # EAGAIN before tearing down.
                    raise OSError(32, "broken pipe")
                return super().send(data)

        sock = _FailOnBodySend()
        sock.enqueue_recv(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, ("127.0.0.1", 1))],
            handler=lambda request: build_streaming_response(
                200, source=_fixed_source(600, 100), content_length=600,
            ),
        )
        _drive_until_idle(server, ticks)
        assert server.in_flight == 0
        assert sock.closed is True

    def test_per_tick_send_budget_bounds_one_connection(self):
        # Body far bigger than the per-tick budget: a single handle() tick
        # must not drain it all — the budget caps bytes-sent-per-tick.
        sock, peer = _connection(request_bytes(path="/big"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(
                200, source=_fixed_source(4000, 4000), content_length=4000,
            ),
            send_budget_per_tick=200,
        )
        server.handle(ticks.ticks_ms())  # one tick only
        # Headers (~59 B) + at most ~2x budget on the transition tick;
        # nowhere near the whole 4000-byte body.
        assert 0 < len(sock.sent) < 4000
        assert server.in_flight == 1  # not done in one tick


class TestStreamingFairness:
    def test_two_streams_interleave_neither_starves(self):
        sock_a = FakeSocket()
        sock_a.enqueue_recv(request_bytes(path="/a"))
        sock_b = FakeSocket()
        sock_b.enqueue_recv(request_bytes(path="/b"))
        server, ticks = _make_server(
            sockets=[(sock_a, ("1", 1)), (sock_b, ("2", 2))],
            handler=lambda request: build_streaming_response(
                200, source=_fixed_source(1000, 1000), content_length=1000,
            ),
            send_budget_per_tick=100,
            max_connections=2,
        )
        # Drive enough ticks for both to accept and start streaming, then
        # snapshot: both must be making progress at once, neither drained
        # while the other stalls.
        for _ in range(6):
            server.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert sock_a.sent.count(b"x") > 0
        assert sock_b.sent.count(b"x") > 0
        assert server.in_flight == 2  # both still streaming, both alive
        _drive_until_idle(server, ticks)
        assert sock_a.sent.count(b"x") == 1000
        assert sock_b.sent.count(b"x") == 1000


class TestStreamingTimeout:
    def test_stalled_client_times_out_mid_stream(self):
        # Headers flush (send call 1), then the client stops reading — every
        # body send EAGAINs forever.  The request-timeout deadline, which
        # covers the whole streamed send, closes the stalled connection.
        class StalledAfterHeaders(FakeSocket):
            def __init__(self):
                super().__init__()
                self._sends = 0

            def send(self, data):
                self._sends += 1
                if self._sends == 1:
                    return super().send(data)  # headers go out
                raise OSError(errno.EAGAIN, "would block")  # body stalls

        sock = StalledAfterHeaders()
        sock.enqueue_recv(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, ("127.0.0.1", 1))],
            handler=lambda request: build_streaming_response(
                200, source=_fixed_source(10000, 500), content_length=10000,
            ),
            request_timeout_ms=50,
        )
        for _ in range(60):
            server.handle(ticks.ticks_ms())
            if server.in_flight == 0:
                break
            ticks.advance(2)
        assert server.in_flight == 0
        assert sock.closed is True
        # The stall was during the body drain: headers made it out first.
        assert sock.sent.startswith(b"HTTP/1.1 200 OK")


class TestStreamingHandlerFailure:
    def test_source_raises_mid_body_closes_connection(self):
        state = {"calls": 0}

        def source(buffer):
            state["calls"] += 1
            if state["calls"] <= 2:
                buffer[:8] = b"goodbyte"
                return 8
            raise RuntimeError("sensor died")

        sock, peer = _connection(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(200, source=source),
        )
        _drive_until_idle(server, ticks)
        # Connection closed; the framing is broken (no terminating chunk),
        # and no error page was spliced into the body.
        assert server.in_flight == 0
        assert sock.closed is True
        assert not bytes(sock.sent).endswith(b"0\r\n\r\n")
        assert b"500" not in bytes(sock.sent).split(b"\r\n\r\n", 1)[-1]

    def test_content_length_short_source_closes_connection(self):
        # Source EOFs after fewer bytes than the declared length: framing
        # is inconsistent, so the connection closes.
        sock, peer = _connection(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(
                200, source=_list_source([b"only-ten!!"]), content_length=100,
            ),
        )
        _drive_until_idle(server, ticks)
        assert server.in_flight == 0
        assert sock.closed is True

    def test_unencodable_streaming_headers_fall_back_to_500(self):
        # A control char in a streaming header can't be encoded; because
        # no body byte has been sent yet, the server falls back to the
        # canned 500 instead of a broken stream.
        sock, peer = _connection(request_bytes(path="/log"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(
                200, source=_list_source([b"data"]),
                headers=[("X-Bad", "a\r\nX-Injected: 1")],
            ),
        )
        _drive_until_idle(server, ticks)
        assert sock.sent.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")


class TestStreamingSourceConventions:
    def test_dry_source_retries_until_data(self):
        # 0 means "no bytes this tick", not EOF: the body arrives on a
        # later tick and the stream completes normally.
        phase = {"n": 0}

        def source(buffer):
            phase["n"] += 1
            if phase["n"] <= 3:
                return 0  # dry three times
            if phase["n"] == 4:
                buffer[:5] = b"ready"
                return 5
            return SOURCE_EOF

        sock, peer = _connection(request_bytes(path="/sensor"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_streaming_response(200, source=source),
        )
        _drive_until_idle(server, ticks)
        _head, body = _split_wire(sock.sent)
        assert _dechunk(body) == b"ready"

    def test_non_streaming_connection_allocates_no_window(self):
        # A buffered response must never mint a staging window — the
        # window is a streaming-only cost.  A tiny send budget keeps the
        # connection in flight long enough to snapshot it mid-drain.
        sock, peer = _connection(request_bytes(path="/plain"))
        server, ticks = _make_server(
            sockets=[(sock, peer)],
            handler=lambda request: build_response(200, text="plain"),
            send_budget_per_tick=4,
        )
        server.handle(ticks.ticks_ms())
        connection = server._connections[0]  # noqa: SLF001
        assert connection._stream is None  # noqa: SLF001
        assert connection._stream_buffer is None  # noqa: SLF001
        _drive_until_idle(server, ticks)
        assert connection._stream is None  # noqa: SLF001
        assert connection._stream_buffer is None  # noqa: SLF001
        assert sock.sent.endswith(b"\r\n\r\nplain")
