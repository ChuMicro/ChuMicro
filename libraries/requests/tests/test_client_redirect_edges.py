"""requests client: redirect edge cases — budget zero, missing/invalid
Location, per-request override, and connector-factory failures.
"""

from _redirect_helpers import _factory_for_socket_sequence, canned_redirect
from chumicro_requests import (
    HttpClient,
    HttpError,
    HttpURLError,
)
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
    make_client,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


class TestHttpClientRedirectEdges:
    """Terminal 3xx, invalid Location, per-request ceiling, factory errors."""

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
            transport_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
            default_max_redirects=1,  # default would block the chain
        )
        handle = client.get(
            "http://example.test/orig", max_redirects=10,  # caller raises ceiling
        )
        drive_until_done(client, handle, ticks, max_ticks=200)
        assert handle.result.body == b"got-here"

    def test_redirect_factory_failure_propagates(self):
        """If the transport_factory raises during a redirect hop the
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
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

        ticks = FakeTicks()
        client = HttpClient(
            transport_factory=factory,
            ticks=ticks,
        )
        handle = client.get("http://example.test/orig")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpError)
        assert "factory failed" in str(handle.error)

    def test_redirect_factory_unexpected_error_does_not_wedge(self):
        """A non-OSError / non-HttpError from the factory during a
        redirect hop resolves the handle with an error instead of
        escaping and leaving it wedged (done=False, error=None)."""
        sockets = [FakeSocket()]
        sockets[0].enqueue_recv(canned_redirect(
            status=301, location="/dest",
        ))
        cursor = {"index": 0}

        def factory(host, port, use_tls):  # noqa: ARG001
            if cursor["index"] >= len(sockets):
                raise ValueError("unexpected boom on redirect")
            socket = sockets[cursor["index"]]
            cursor["index"] += 1
            return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

        ticks = FakeTicks()
        client = HttpClient(transport_factory=factory, ticks=ticks)
        handle = client.get("http://example.test/orig")
        drive_until_done(client, handle, ticks)
        assert isinstance(handle.error, HttpError)
        assert "redirect hop failed" in str(handle.error)
        assert client.busy is False
