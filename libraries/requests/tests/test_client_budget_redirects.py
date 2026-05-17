"""requests client: recv budget, oversize policy, redirects."""

from chumicro_requests import (
    HttpClient,
    HttpError,
    HttpOversizedError,
    HttpURLError,
    WhenOversized,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def make_factory(socket_or_factory):
    """Return a connection_factory that hands out *socket_or_factory*.

    *socket_or_factory* can be either a single :class:`FakeSocket`
    (returned every call) or a zero-arg callable that builds a fresh
    one on demand.
    """
    def factory(host, port, use_tls):  # noqa: ARG001 — fake ignores args
        if callable(socket_or_factory):
            return socket_or_factory()
        return socket_or_factory

    return factory

def canned_response(*, status=200, reason="OK", body=b"", extra_headers=()):
    """Build an HTTP/1.1 response byte-string with Content-Length."""
    lines = [f"HTTP/1.1 {status} {reason}\r\n".encode("ascii")]
    lines.append(f"Content-Length: {len(body)}\r\n".encode("ascii"))
    lines.append(b"Content-Type: text/plain\r\n")
    for name, value in extra_headers:
        lines.append(f"{name}: {value}\r\n".encode("ascii"))
    lines.append(b"\r\n")
    lines.append(body)
    return b"".join(lines)

def canned_redirect(*, status=301, location="/", reason="Moved"):
    """Build an HTTP/1.1 3xx redirect response byte-string."""
    return (
        f"HTTP/1.1 {status} {reason}\r\n"
        f"Location: {location}\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    ).encode("ascii")

def drive_until_done(client, handle, ticks, *, max_ticks=200, advance_ms=1):
    """Run handle/check until done; safety-cap at *max_ticks* iterations."""
    for _ in range(max_ticks):
        if handle.done:
            return
        if client.check(ticks.ticks_ms()):
            client.handle(ticks.ticks_ms())
        ticks.advance(advance_ms)
    raise AssertionError(f"handle never completed within {max_ticks} ticks")

def make_client(*, socket_or_factory=None, **kwargs):
    """Construct an HttpClient wired to FakeTicks + a FakeSocket factory."""
    ticks = FakeTicks()
    socket = socket_or_factory if socket_or_factory is not None else FakeSocket()
    client = HttpClient(
        connection_factory=make_factory(socket),
        ticks=ticks,
        **kwargs,
    )
    return client, ticks, socket

class _CountingSocket(FakeSocket):
    """FakeSocket that records bytes consumed per recv_into call."""

    def __init__(self):
        super().__init__()
        self.bytes_received_total = 0

    def recv_into(self, buffer, nbytes=0):
        result = super().recv_into(buffer, nbytes)
        if result > 0:
            self.bytes_received_total += result
        return result

def _factory_for_socket_sequence(sockets):
    """Return a connection_factory that hands out *sockets* FIFO."""
    cursor = {"index": 0}

    def factory(host, port, use_tls):  # noqa: ARG001
        socket = sockets[cursor["index"]]
        cursor["index"] += 1
        return socket

    return factory


class TestHttpClientRecvBudget:
    """``recv_budget_per_tick`` keeps each tick LED-friendly."""

    def test_budget_caps_bytes_per_tick(self):
        body = b"x" * 4096
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            recv_budget_per_tick=512,
            max_body_bytes=8192,
        )
        handle = client.get("http://example.test/")
        # Drive sending only — first tick handles SENDING + transitions to RECEIVING.
        client.handle(ticks.ticks_ms())  # SEND
        socket.bytes_received_total = 0
        client.handle(ticks.ticks_ms())  # RECV (one tick)
        assert socket.bytes_received_total <= 512
        assert not handle.done

    def test_default_budget_is_1024(self):
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=b"x" * 8192))
        client, ticks, _ = make_client(
            socket_or_factory=socket, max_body_bytes=16384,
        )
        handle = client.get("http://example.test/")
        client.handle(ticks.ticks_ms())  # SEND
        socket.bytes_received_total = 0
        client.handle(ticks.ticks_ms())  # RECV (one tick)
        assert socket.bytes_received_total <= 1024
        assert not handle.done

    def test_budget_eventually_drains_full_payload(self):
        body = b"y" * 4096
        socket = _CountingSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            recv_budget_per_tick=1024,
            max_body_bytes=8192,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks, max_ticks=20)
        assert handle.result.body == body


class TestHttpClientOversizePolicy:
    """``WhenOversized`` branches: silent drop, drop+event, fail."""

    def test_drop_silent_yields_empty_body(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DROP_SILENT,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        response = handle.result
        assert response.body == b""
        assert response.oversized_dropped is True
        assert response.status_code == 200

    def test_drop_with_event_fires_callback(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DROP_WITH_EVENT,
        )
        events = []
        client.on_oversized = lambda reported_length, url: events.append((reported_length, url))

        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert handle.result.oversized_dropped is True
        assert len(events) == 1
        assert events[0][0] == 100
        assert events[0][1] == "http://example.test/"

    def test_disconnect_policy_fails_request(self):
        body = b"x" * 100
        socket = FakeSocket()
        socket.enqueue_recv(canned_response(body=body))
        client, ticks, _ = make_client(
            socket_or_factory=socket,
            max_body_bytes=10,
            when_oversized=WhenOversized.DISCONNECT,
        )
        handle = client.get("http://example.test/")
        drive_until_done(client, handle, ticks)

        assert isinstance(handle.error, HttpOversizedError)
        assert handle.error.reported_length == 100


class TestHttpClientRedirects:
    """3xx + Location handling with the per-request budget."""

    def _make_redirect_chain(self, urls_and_destinations, *, final_body=b"final"):
        """Build a list of FakeSockets that respond with redirects then a 200.

        *urls_and_destinations* is a list of ``(status, location)`` tuples,
        one per redirect hop.  The final socket returns 200 with *final_body*.
        """
        sockets = []
        for status, location in urls_and_destinations:
            socket = FakeSocket()
            socket.enqueue_recv(canned_redirect(status=status, location=location))
            sockets.append(socket)
        terminal = FakeSocket()
        terminal.enqueue_recv(canned_response(body=final_body))
        sockets.append(terminal)
        return sockets

    def test_301_followed_to_absolute_url(self):
        sockets = self._make_redirect_chain([
            (301, "http://example.test/v2/widgets"),
        ], final_body=b"widget-list")
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.get("http://example.test/v1/widgets")
        drive_until_done(client, handle, ticks)
        response = handle.result
        assert response.status_code == 200
        assert response.body == b"widget-list"
        # Final URL reflects the destination, not the original.
        assert response.url == "http://example.test/v2/widgets"

    def test_302_absolute_path_redirect(self):
        sockets = self._make_redirect_chain([(302, "/relocated")])
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.get("http://example.test/orig")
        drive_until_done(client, handle, ticks)
        response = handle.result
        assert response.status_code == 200
        # Second request hits /relocated on the same host.
        assert b"GET /relocated HTTP/1.1\r\n" in sockets[1].sent

    def test_303_post_becomes_get(self):
        """RFC 7231 §6.4.4: 303 always switches the next hop to GET."""
        sockets = self._make_redirect_chain([(303, "/result")])
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.post("http://example.test/submit", body=b"payload")
        drive_until_done(client, handle, ticks)
        # First hop is POST with body; second hop must be GET, no body.
        assert sockets[0].sent.startswith(b"POST /submit HTTP/1.1\r\n")
        assert b"\r\n\r\npayload" in sockets[0].sent
        assert sockets[1].sent.startswith(b"GET /result HTTP/1.1\r\n")
        assert sockets[1].sent.endswith(b"\r\n\r\n")
        assert b"Content-Length:" not in sockets[1].sent

    def test_307_preserves_method_and_body(self):
        """RFC 7231 §6.4.7: 307 must replay the original method + body."""
        sockets = self._make_redirect_chain([(307, "/replay")])
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.post("http://example.test/orig", body=b"replay-me")
        drive_until_done(client, handle, ticks)
        # Both hops are POST with the same body.
        assert sockets[0].sent.startswith(b"POST /orig HTTP/1.1\r\n")
        assert sockets[0].sent.endswith(b"\r\n\r\nreplay-me")
        assert sockets[1].sent.startswith(b"POST /replay HTTP/1.1\r\n")
        assert sockets[1].sent.endswith(b"\r\n\r\nreplay-me")

    def test_308_preserves_method_and_json_body(self):
        sockets = self._make_redirect_chain([(308, "/permanent")])
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.post(
            "http://example.test/orig", json={"key": "value"},
        )
        drive_until_done(client, handle, ticks)
        # Both hops POST with the same JSON body + content-type default.
        assert sockets[0].sent.startswith(b"POST /orig HTTP/1.1\r\n")
        assert b"Content-Type: application/json\r\n" in sockets[0].sent
        assert sockets[1].sent.startswith(b"POST /permanent HTTP/1.1\r\n")
        assert b"Content-Type: application/json\r\n" in sockets[1].sent

    def test_max_redirects_zero_returns_3xx_as_is(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_redirect(status=301, location="/elsewhere"))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/orig", max_redirects=0)
        drive_until_done(client, handle, ticks)
        response = handle.result
        assert response.status_code == 301
        assert response.headers["location"] == "/elsewhere"
        assert response.url == "http://example.test/orig"

    def test_redirect_chain_within_budget(self):
        """5 hops with default budget 5 — exactly at the limit."""
        sockets = self._make_redirect_chain([
            (302, "/hop2"), (302, "/hop3"),
            (302, "/hop4"), (302, "/hop5"),
            (302, "/final"),
        ], final_body=b"reached")
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.get("http://example.test/orig")  # default budget = 5
        drive_until_done(client, handle, ticks, max_ticks=400)
        response = handle.result
        assert response.body == b"reached"

    def test_redirect_chain_exceeds_budget(self):
        """6 hops with budget 5 — final 302 returned as-is when budget hits 0."""
        sockets = self._make_redirect_chain([
            (302, "/hop2"), (302, "/hop3"),
            (302, "/hop4"), (302, "/hop5"),
            (302, "/hop6"), (302, "/final"),
        ])
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.get("http://example.test/orig", max_redirects=5)
        drive_until_done(client, handle, ticks, max_ticks=400)
        # After 5 hops the budget is exhausted; the 6th 302 is returned
        # to the caller as-is rather than followed.
        response = handle.result
        assert response.status_code == 302
        assert response.headers["location"] == "/final"

    def test_3xx_without_location_returned_as_is(self):
        """Treats a 3xx with no Location as a terminal response."""
        socket = FakeSocket()
        socket.enqueue_recv(
            b"HTTP/1.1 301 Moved\r\nContent-Length: 0\r\n\r\n",
        )
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/orig")
        drive_until_done(client, handle, ticks)
        response = handle.result
        assert response.status_code == 301

    def test_redirect_with_invalid_location_fails(self):
        socket = FakeSocket()
        socket.enqueue_recv(canned_redirect(
            status=301, location="ftp://wrong-scheme/dest",
        ))
        client, ticks, _ = make_client(socket_or_factory=socket)
        handle = client.get("http://example.test/orig")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpURLError)

    def test_per_request_max_redirects_overrides_default(self):
        sockets = self._make_redirect_chain([
            (302, "/hop2"), (302, "/hop3"),
        ], final_body=b"got-here")
        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
            default_max_redirects=1,  # default would block the chain
        )
        handle = client.get(
            "http://example.test/orig", max_redirects=10,  # caller raises ceiling
        )
        drive_until_done(client, handle, ticks, max_ticks=200)
        assert handle.result.body == b"got-here"

    def test_redirect_factory_failure_propagates(self):
        """If the connection_factory raises during a redirect hop the
        request fails cleanly with the wrapped error."""
        sockets = [FakeSocket()]
        sockets[0].enqueue_recv(canned_redirect(
            status=301, location="/dest",
        ))
        cursor = {"index": 0}

        def factory(host, port, use_tls):  # noqa: ARG001
            if cursor["index"] >= len(sockets):
                raise OSError(99, "factory boom on redirect")
            socket = sockets[cursor["index"]]
            cursor["index"] += 1
            return socket

        ticks = FakeTicks()
        client = HttpClient(
            connection_factory=factory,
            ticks=ticks,
        )
        handle = client.get("http://example.test/orig")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpError)
        assert "factory failed" in str(handle.error)
