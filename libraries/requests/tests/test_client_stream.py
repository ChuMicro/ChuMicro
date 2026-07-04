"""requests client: ``stream=True`` — Content-Length streaming end to end.

Headers-early publish, caller-buffer drains across ticks, EOF contract,
backpressure against a full staging window, redirect hops, cancel, and
the guards on the buffered-only conveniences.
"""

from chumicro_requests import HttpError, WhenOversized
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_test_harness import raises


def _stream_until_done(client, handle, ticks, *, read_size=32, max_ticks=400):
    """Drive *client* and drain *handle* per tick; return the body bytes.

    The consumer-service loop from the guide, flattened for tests: one
    ``handle()`` tick, then one ``read_body_into`` into a caller-owned
    buffer, until ``done`` and the staging is drained.
    """
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


class TestStreamContentLength:
    """Content-Length bodies stream through the staging window."""

    def test_body_arrives_through_caller_buffer(self):
        body = bytes(range(256)) * 8  # 2 KB
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(socket_or_factory=socket)

        handle = client.get("http://example.test/big", stream=True)
        collected = _stream_until_done(client, handle, ticks)

        assert collected == body
        assert handle.result.status_code == 200
        assert handle.result.streamed is True
        assert handle.result.body == b""
        assert socket.closed is True
        assert client.busy is False

    def test_response_publishes_before_done(self):
        """Status and headers surface on handle.response while the body
        is still arriving — before handle.done flips."""
        body = b"x" * 512
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket, recv_budget_per_tick=128,
        )
        handle = client.get("http://example.test/", stream=True)
        for _ in range(50):
            if handle.response is not None:
                break
            client.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert handle.response is not None
        assert handle.done is False
        assert handle.response.status_code == 200
        assert handle.response.headers["content-type"] == "text/plain"

    def test_zero_after_done_is_end_of_body(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"tail"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", stream=True)
        collected = _stream_until_done(client, handle, ticks)
        assert collected == b"tail"
        # Every read after the drain keeps returning 0.
        assert handle.read_body_into(bytearray(8)) == 0

    def test_no_body_status_streams_as_immediate_eof(self):
        """A 204 with stream=True publishes headers and ends at once:
        the first read after done reports end of body."""
        socket = FakeSocket()
        socket.enqueue_recv(b"HTTP/1.1 204 No Content\r\n\r\n")
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", stream=True)
        collected = _stream_until_done(client, handle, ticks)
        assert collected == b""
        assert handle.result.status_code == 204
        assert handle.result.streamed is True

    def test_body_over_max_body_bytes_streams(self):
        """The whole point: a body past max_body_bytes is consumable with
        stream=True (the same cap fails the buffered request)."""
        body = b"f" * 3000
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=100,
            when_oversized=WhenOversized.DISCONNECT,
        )
        handle = client.get("http://example.test/firmware", stream=True)
        collected = _stream_until_done(client, handle, ticks)
        assert collected == body
        assert handle.error is None


class TestStreamBackpressure:
    """A full staging window stops the socket drain until the caller reads."""

    def test_recv_pauses_at_window_capacity(self):
        body = b"q" * 512
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket, stream_buffer_size=64,
        )
        handle = client.get("http://example.test/", stream=True)
        # Drive without reading: the client parses headers, stages 64
        # body bytes, then stalls — io_interest drops to 0 so the
        # runner parks instead of spinning on the readable socket.
        for _ in range(20):
            client.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert handle.response is not None
        assert handle.done is False
        assert client.io_interest(ticks.ticks_ms()) == 0
        # Draining reopens read interest (bit value 1 == IO_READ) and
        # the transfer completes.
        assert handle.read_body_into(bytearray(64)) == 64
        assert client.io_interest(ticks.ticks_ms()) == 1
        collected = _stream_until_done(client, handle, ticks)
        assert b"q" * 64 + collected == body


class TestStreamRedirects:
    """Redirect hops are followed; their bodies are never delivered."""

    def test_hop_body_discarded_and_final_streams(self):
        first = FakeSocket()
        first.enqueue_recv(canned_response(
            status=302, reason="Found", body=b"MOVED-BODY",
            extra_headers=[("Location", "/next")],
        ))
        second = FakeSocket()
        second.enqueue_recv(canned_response(body=b"final-payload"))
        sockets = [first, second]
        client, ticks, _ = make_client(socket_or_factory=lambda: sockets.pop(0))

        handle = client.get("http://example.test/start", stream=True)
        collected = _stream_until_done(client, handle, ticks)

        assert collected == b"final-payload"
        assert handle.result.status_code == 200
        assert handle.result.url == "http://example.test/next"

    def test_exhausted_budget_publishes_the_3xx(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(
            status=302, reason="Found", body=b"halted",
            extra_headers=[("Location", "/next")],
        ))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get(
            "http://example.test/", stream=True, max_redirects=0,
        )
        collected = _stream_until_done(client, handle, ticks)
        assert handle.result.status_code == 302
        assert collected == b"halted"


class TestStreamGuards:
    """Buffered-only conveniences refuse loudly on streamed exchanges."""

    def test_text_and_json_raise_on_streamed_response(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"{}"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/", stream=True)
        _stream_until_done(client, handle, ticks)
        response = handle.result
        with raises(HttpError):
            _ = response.text
        with raises(HttpError):
            response.json()

    def test_read_body_into_requires_stream_request(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"ok"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)
        with raises(HttpError):
            handle.read_body_into(bytearray(8))


class TestClientCancel:
    """``HttpClient.cancel`` aborts the in-flight request."""

    def test_cancel_mid_stream_fails_handle_and_closes_socket(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=b"m" * 2048))
        client, ticks, _ = make_client(
            socket_or_factory=socket, stream_buffer_size=64,
        )
        handle = client.get("http://example.test/", stream=True)
        for _ in range(10):
            client.handle(ticks.ticks_ms())
            ticks.advance(1)
        assert handle.done is False

        client.cancel()

        assert handle.done is True
        assert isinstance(handle.error, HttpError)
        assert "cancelled" in str(handle.error)
        assert socket.closed is True
        assert client.busy is False

    def test_cancel_when_idle_is_noop(self):
        client, ticks, _ = make_client()
        client.cancel()
        assert client.busy is False

    def test_cancel_fires_on_done(self):
        socket = FakeSocket()
        completions = []
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get(
            "http://example.test/", on_done=completions.append,
        )
        client.cancel()
        assert completions == [handle]
        assert handle.done is True
