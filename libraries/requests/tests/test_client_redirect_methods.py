"""requests client: 3xx redirect method/body semantics (301/302/303/307/308)."""

from _redirect_helpers import _factory_for_socket_sequence, canned_redirect
from chumicro_requests import HttpClient
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestHttpClientRedirectMethods:
    """3xx status handling: which method/body the next hop replays."""

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
            transport_factory=_factory_for_socket_sequence(sockets),
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
            transport_factory=_factory_for_socket_sequence(sockets),
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
            transport_factory=_factory_for_socket_sequence(sockets),
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
            transport_factory=_factory_for_socket_sequence(sockets),
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
            transport_factory=_factory_for_socket_sequence(sockets),
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
