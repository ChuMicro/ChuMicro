"""First-association grace for ``WifiService``.

Cross-runtime: runs on CPython pytest and under the MicroPython +
CircuitPython unix-ports.  A board's first wifi association after
power-up takes longer than a steady-state reconnect, so
``first_connect_timeout_ms`` gives the first dispatched connect attempt
its own, longer allowance.  These pin the config plumbing, the
per-attempt allowance handed to a blocking adapter, the in-flight poll
window on a non-blocking adapter, and that every attempt after the
first (reconnects included) uses ``connect_timeout_ms`` unchanged.
"""

from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiConfig, WifiService, WifiState
from chumicro_wifi.testing import FakeWifiAdapter


def _service(*, config_overrides=None):
    """Build a WifiService against a FakeWifiAdapter + FakeTicks for tests."""
    base = {
        "ssid": "testnet",
        "password": "password",
        "reconnect_backoff_start_ms": 10,
        "reconnect_backoff_max_ms": 100,
    }
    if config_overrides is not None:
        base.update(config_overrides)
    config = WifiConfig(**base)
    ticks = FakeTicks()
    adapter = FakeWifiAdapter()
    service = WifiService(config, adapter=adapter, ticks=ticks)
    return service, ticks, adapter


def _connect_timeouts(adapter):
    """Per-attempt timeout_ms values, in dispatch order, from the fake's call log."""
    return [call[2] for call in adapter.calls if call[0] == "connect"]


class _BoomError(Exception):
    """Stand-in for an adapter failure raised on the first attempt."""


# ---------------------------------------------------------------------------
# WifiConfig plumbing
# ---------------------------------------------------------------------------


def test_config_defaults_to_no_grace() -> None:
    """``first_connect_timeout_ms`` defaults to ``None`` on direct
    construction and through ``from_config``."""
    assert WifiConfig(ssid="x", password="y").first_connect_timeout_ms is None
    loaded = WifiConfig.from_config({"wifi.ssid": "x", "wifi.password": "y"})
    assert loaded.first_connect_timeout_ms is None


def test_config_from_config_reads_the_flat_key() -> None:
    """``wifi.first_connect_timeout_ms`` loads through the flat-key factory."""
    loaded = WifiConfig.from_config(
        {
            "wifi.ssid": "x",
            "wifi.password": "y",
            "wifi.first_connect_timeout_ms": 45_000,
        },
    )
    assert loaded.first_connect_timeout_ms == 45_000


# ---------------------------------------------------------------------------
# Blocking substrate: the allowance handed to connect()
# ---------------------------------------------------------------------------


def test_first_attempt_carries_grace_then_retries_use_connect_timeout() -> None:
    """With the grace set, the first dispatched connect is handed
    ``first_connect_timeout_ms`` and the retry after its failure is
    handed ``connect_timeout_ms``."""
    service, ticks, adapter = _service(
        config_overrides={"first_connect_timeout_ms": 45_000},
    )
    adapter.set_connect_outcomes([False, False])

    service.handle(ticks.ticks_ms())  # first attempt: cold radio
    ticks.advance(10)
    service.handle(ticks.ticks_ms())  # retry: warm radio

    assert _connect_timeouts(adapter) == [45_000, 15_000]


def test_without_grace_every_attempt_uses_connect_timeout() -> None:
    """With ``first_connect_timeout_ms`` left ``None`` (the default), the
    first attempt and the retry both carry ``connect_timeout_ms``."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcomes([False, False])

    service.handle(ticks.ticks_ms())
    ticks.advance(10)
    service.handle(ticks.ticks_ms())

    assert _connect_timeouts(adapter) == [15_000, 15_000]


def test_reconnect_after_first_connected_uses_connect_timeout() -> None:
    """A reconnect after the first CONNECTED is handed
    ``connect_timeout_ms``: the grace never reapplies after the first
    dispatched attempt."""
    service, ticks, adapter = _service(
        config_overrides={"first_connect_timeout_ms": 45_000},
    )
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())
    assert service.state == WifiState.CONNECTED

    adapter.drop_link()
    service.handle(ticks.ticks_ms())  # detect drop -> RECONNECTING
    service.handle(ticks.ticks_ms())  # reconnect attempt
    assert service.state == WifiState.CONNECTED
    assert _connect_timeouts(adapter) == [45_000, 15_000]


def test_raising_first_connect_consumes_the_grace() -> None:
    """A first connect() that raises still consumes the grace: the dial
    touched the radio, so the retry carries ``connect_timeout_ms``."""
    service, ticks, adapter = _service(
        config_overrides={"first_connect_timeout_ms": 45_000},
    )
    adapter.set_connect_outcomes([_BoomError, False])

    service.handle(ticks.ticks_ms())
    assert isinstance(service.last_error, _BoomError)
    ticks.advance(10)
    service.handle(ticks.ticks_ms())

    assert _connect_timeouts(adapter) == [45_000, 15_000]


# ---------------------------------------------------------------------------
# Non-blocking substrate: the in-flight poll window
# ---------------------------------------------------------------------------


def test_grace_extends_nonblocking_poll_window() -> None:
    """On a non-blocking substrate the first join's in-flight window runs
    to ``first_connect_timeout_ms``: past ``connect_timeout_ms`` the
    attempt is still in flight with no failure counted, and past the
    grace it settles as one failed attempt."""
    service, ticks, adapter = _service(
        config_overrides={
            "connect_timeout_ms": 1_000,
            "first_connect_timeout_ms": 5_000,
        },
    )
    adapter.set_connect_blocks(False)
    adapter.set_connect_outcome(False)

    service.handle(ticks.ticks_ms())  # dispatch the join, arm the grace window
    ticks.advance(1_500)  # past connect_timeout_ms, inside the grace
    service.handle(ticks.ticks_ms())
    assert service._attempt_deadline_ms is not None  # noqa: SLF001 - still in flight
    assert service._reconnect_attempts == 0  # noqa: SLF001 - no failure counted

    ticks.advance(4_000)  # past the grace
    service.handle(ticks.ticks_ms())
    assert service._attempt_deadline_ms is None  # noqa: SLF001 - window closed
    assert service._reconnect_attempts == 1  # noqa: SLF001 - settled failure


def test_nonblocking_link_inside_grace_window_reaches_connected() -> None:
    """A cold join that links after ``connect_timeout_ms`` but inside the
    grace window still reaches CONNECTED, which is the whole point of the
    first-association grace."""
    service, ticks, adapter = _service(
        config_overrides={
            "connect_timeout_ms": 1_000,
            "first_connect_timeout_ms": 5_000,
        },
    )
    adapter.set_deferred_link(link_after=1)

    service.handle(ticks.ticks_ms())  # dispatch the join
    ticks.advance(2_000)  # a wait that would have exhausted connect_timeout_ms
    service.handle(ticks.ticks_ms())  # poll: link is up

    assert service.state == WifiState.CONNECTED


# ---------------------------------------------------------------------------
# FakeWifiAdapter call-record shape the assertions above rely on
# ---------------------------------------------------------------------------


def test_fake_adapter_records_none_timeout_on_direct_calls() -> None:
    """A direct ``connect(config)`` call (no service, no explicit
    allowance) records ``timeout_ms`` as ``None``."""
    adapter = FakeWifiAdapter()
    config = WifiConfig(ssid="x", password="y")
    adapter.connect(config)
    assert adapter.calls == [("connect", config, None)]
