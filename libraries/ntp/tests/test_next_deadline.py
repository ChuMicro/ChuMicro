"""``NTPClient.next_deadline``: the tick ``Runner.wait()`` sleeps toward.

Cross-runtime lane: plain asserts against ``FakeUDPSocket`` and
``FakeTicks``, runs on CPython and both device runtimes.
"""

from chumicro_ntp import NTPClient
from chumicro_sockets.testing import FakeUDPSocket
from chumicro_timing.testing import FakeTicks


def _client(*, timeout_ms=5_000):
    """Build an NTPClient over a FakeUDPSocket and FakeTicks."""
    ticks = FakeTicks()
    client = NTPClient(socket=FakeUDPSocket(), timeout_ms=timeout_ms, ticks=ticks)
    return client, ticks


def test_idle_client_reports_no_deadline() -> None:
    """With no query issued, the client gives wait() nothing to wake for."""
    client, ticks = _client()
    assert client.next_deadline(ticks.ticks_ms()) is None


def test_in_flight_query_polls_every_20_ms() -> None:
    """While a reply is outstanding, the deadline is 20 ms out."""
    client, ticks = _client()
    client.query()
    now_ms = ticks.ticks_ms()
    assert client.next_deadline(now_ms) == now_ms + 20


def test_poll_past_the_timeout_fails_the_query() -> None:
    """The first 20 ms turn after ``timeout_ms`` fails the query, so the
    timeout lands at most one poll late."""
    client, ticks = _client(timeout_ms=100)
    request = client.query()
    ticks.advance(90)
    now_ms = ticks.ticks_ms()
    next_turn = client.next_deadline(now_ms)
    assert next_turn == now_ms + 20
    ticks.advance(20)
    client.handle(ticks.ticks_ms())
    assert request.done
    assert request.error is not None


def test_finished_query_reports_no_deadline() -> None:
    """A canceled query is done, so the deadline goes back to None."""
    client, ticks = _client()
    client.query()
    client.cancel()
    assert client.next_deadline(ticks.ticks_ms()) is None
