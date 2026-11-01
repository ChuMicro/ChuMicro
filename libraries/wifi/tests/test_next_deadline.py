"""``WifiService.next_deadline``: the tick ``Runner.wait()`` sleeps toward.

Cross-runtime lane: plain asserts against ``FakeWifiAdapter`` and
``FakeTicks``, runs on CPython and both device runtimes.
"""

from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiConfig, WifiService, WifiState
from chumicro_wifi.testing import FakeWifiAdapter


def _service(*, config_overrides=None):
    """Build a WifiService against a FakeWifiAdapter + FakeTicks for tests."""
    base = {
        "ssid": "testnet",
        "password": "password",
        "reconnect_backoff_start_ms": 2_000,
        "reconnect_backoff_max_ms": 8_000,
    }
    if config_overrides is not None:
        base.update(config_overrides)
    ticks = FakeTicks()
    adapter = FakeWifiAdapter()
    service = WifiService(WifiConfig(**base), adapter=adapter, ticks=ticks)
    return service, ticks, adapter


def test_fresh_service_reports_its_first_attempt_as_due_now() -> None:
    """Before the first handle(), the deadline is the construction tick, so wait() returns at once."""
    service, ticks, _adapter = _service()
    now_ms = ticks.ticks_ms()
    assert service.next_deadline(now_ms) == now_ms


def test_backoff_reports_the_next_reconnect_attempt() -> None:
    """After a failed blocking attempt, the deadline is the backoff tick, not now."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(False)
    start_ms = ticks.ticks_ms()
    service.handle(start_ms)
    assert service.state == WifiState.CONNECTING
    assert service.next_deadline(start_ms) == start_ms + 2_000


def test_in_flight_join_polls_every_100_ms() -> None:
    """A non-blocking join in flight asks for a turn 100 ms out."""
    service, ticks, adapter = _service()
    adapter.set_connect_blocks(False)
    adapter.set_deferred_link(link_after=50)
    start_ms = ticks.ticks_ms()
    service.handle(start_ms)
    assert service.state == WifiState.CONNECTING
    assert service.next_deadline(start_ms) == start_ms + 100


def test_poll_past_the_join_timeout_settles_it_as_failed() -> None:
    """The first 100 ms turn after the join timeout counts a failed attempt
    and moves the deadline to the backoff tick."""
    service, ticks, adapter = _service(config_overrides={"connect_timeout_ms": 250})
    adapter.set_connect_blocks(False)
    adapter.set_deferred_link(link_after=50)
    service.handle(ticks.ticks_ms())
    ticks.advance(200)
    now_ms = ticks.ticks_ms()
    assert service.next_deadline(now_ms) == now_ms + 100
    ticks.advance(100)
    now_ms = ticks.ticks_ms()
    service.handle(now_ms)
    assert service.state == WifiState.CONNECTING
    assert service.next_deadline(now_ms) == now_ms + 2_000


def test_connected_reports_a_link_check_one_second_out() -> None:
    """While linked, the deadline is one second out so a drop is noticed."""
    service, ticks, _adapter = _service()
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED
    now_ms = ticks.ticks_ms()
    assert service.next_deadline(now_ms) == now_ms + 1_000


def test_failed_reports_no_deadline() -> None:
    """FAILED has no further work, so it gives wait() nothing to wake for."""
    service, ticks, adapter = _service(config_overrides={"reconnect_max": 1})
    adapter.set_connect_outcome(False)
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.FAILED
    assert service.next_deadline(ticks.ticks_ms()) is None


def test_reconnecting_after_a_drop_is_due_at_once() -> None:
    """The handle() that notices a drop schedules the reconnect for that same tick."""
    service, ticks, adapter = _service()
    service.handle(ticks.ticks_ms())
    adapter.drop_link()
    now_ms = ticks.ticks_ms()
    service.handle(now_ms)
    assert service.state == WifiState.RECONNECTING
    assert service.next_deadline(now_ms) == now_ms
