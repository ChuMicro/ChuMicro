"""requests client: multi-hop redirect chains against the redirect budget.

These build a full sequence of FakeSockets (one per hop plus a terminal)
that coexist while the client walks the chain, so they are the most
allocation-heavy tests in the requests suite and set its heap floor.
"""

from _redirect_helpers import _factory_for_socket_sequence, canned_redirect
from chumicro_requests import HttpClient
from chumicro_requests.testing import (
    canned_response,
    drive_until_done,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class TestHttpClientRedirectChain:
    """Multi-hop 302 chains at, and one past, the redirect budget."""

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

    def test_redirect_chain_within_budget(self):
        """5 hops with default budget 5 — exactly at the limit."""
        sockets = self._make_redirect_chain([
            (302, "/hop2"), (302, "/hop3"),
            (302, "/hop4"), (302, "/hop5"),
            (302, "/final"),
        ], final_body=b"reached")
        ticks = FakeTicks()
        client = HttpClient(
            transport_factory=_factory_for_socket_sequence(sockets),
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
            transport_factory=_factory_for_socket_sequence(sockets),
            ticks=ticks,
        )
        handle = client.get("http://example.test/orig", max_redirects=5)
        drive_until_done(client, handle, ticks, max_ticks=400)
        # After 5 hops the budget is exhausted; the 6th 302 is returned
        # to the caller as-is rather than followed.
        response = handle.result
        assert response.status_code == 302
        assert response.headers["location"] == "/final"
