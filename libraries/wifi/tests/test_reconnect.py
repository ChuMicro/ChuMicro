"""Disconnect -> reconnect story for ``WifiService`` (audit hardening).

The library's headline promise is re-establishing the link after a
mid-session drop without restarting the board.  These exercise the full
drop -> RECONNECTING -> backoff -> reassociate -> callback cycle, a
flapping link, repeated cycles, a connect() that raises mid-reconnect,
the non-blocking in-flight window, a raising state callback, and the
FAILED-exhaustion boundary — plus the ``FakeWifiAdapter`` /
``FakeWifi`` test hooks these rely on.

Split out of ``test_wifi.py`` so each module stays within the
CircuitPython unix-port heap budget when the cross-runtime lanes load
it on the device.
"""

from chumicro_timing.testing import FakeTicks
from chumicro_wifi import WifiConfig, WifiService, WifiState
from chumicro_wifi.testing import FakeWifi, FakeWifiAdapter


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


class _DropError(Exception):
    """Stand-in for a transient adapter failure raised mid-reconnect."""


# ---------------------------------------------------------------------------
# Full drop -> RECONNECTING -> backoff -> reassociate -> callbacks
# ---------------------------------------------------------------------------


def test_full_reconnect_cycle_fires_state_callbacks() -> None:
    """A mid-session drop drives CONNECTED -> RECONNECTING -> (backoff) ->
    CONNECTED and fires exactly the boundary transitions — failed retries
    stay in RECONNECTING and fire nothing."""
    transitions = []
    service, ticks, adapter = _service()
    service.on_state_change(lambda old, new: transitions.append((old, new)))
    # Initial connect, then two failed reconnects, then success.
    adapter.set_connect_outcomes([True, False, False, True])

    service.handle(ticks.ticks_ms())  # DISCONNECTED -> CONNECTING -> CONNECTED
    assert service.state == WifiState.CONNECTED

    adapter.drop_link()
    service.handle(ticks.ticks_ms())  # detect drop -> RECONNECTING
    assert service.state == WifiState.RECONNECTING

    service.handle(ticks.ticks_ms())  # reconnect attempt 1: False, backoff 10
    assert service.state == WifiState.RECONNECTING
    ticks.advance(10)
    service.handle(ticks.ticks_ms())  # reconnect attempt 2: False, backoff 20
    assert service.state == WifiState.RECONNECTING
    ticks.advance(20)
    service.handle(ticks.ticks_ms())  # reconnect attempt 3: True -> CONNECTED
    assert service.state == WifiState.CONNECTED

    assert transitions == [
        (WifiState.DISCONNECTED, WifiState.CONNECTING),
        (WifiState.CONNECTING, WifiState.CONNECTED),
        (WifiState.CONNECTED, WifiState.RECONNECTING),
        (WifiState.RECONNECTING, WifiState.CONNECTED),
    ]
    assert service.last_error is None


def test_reassociation_resets_attempts_and_backoff() -> None:
    """Reaching CONNECTED after retries clears the attempt count and backoff,
    so the next outage starts from a fresh schedule (not a stale one)."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcomes([True, False, True])
    service.handle(ticks.ticks_ms())  # CONNECTED

    adapter.drop_link()
    service.handle(ticks.ticks_ms())  # RECONNECTING
    service.handle(ticks.ticks_ms())  # attempt: False -> attempts=1, backoff 20
    assert service._reconnect_attempts == 1  # noqa: SLF001
    ticks.advance(10)
    service.handle(ticks.ticks_ms())  # attempt: True -> CONNECTED

    assert service.state == WifiState.CONNECTED
    assert service._reconnect_attempts == 0  # noqa: SLF001
    assert service._current_backoff_ms == 10  # noqa: SLF001


def test_repeated_drop_reconnect_cycles_stay_healthy() -> None:
    """Many outage/recovery cycles in a row each recover cleanly, with the
    attempt count + backoff reset every time — no cross-cycle drift."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())  # CONNECTED
    assert service.state == WifiState.CONNECTED

    for cycle in range(4):
        # One failed reconnect then success, to prove attempts reset.
        adapter.set_connect_outcomes([False, True])
        adapter.drop_link()
        service.handle(ticks.ticks_ms())  # detect -> RECONNECTING
        assert service.state == WifiState.RECONNECTING
        service.handle(ticks.ticks_ms())  # attempt: False -> attempts=1
        assert service._reconnect_attempts == 1  # noqa: SLF001
        ticks.advance(10)
        service.handle(ticks.ticks_ms())  # attempt: True -> CONNECTED
        assert service.state == WifiState.CONNECTED, f"cycle {cycle}"
        assert service._reconnect_attempts == 0  # noqa: SLF001
        assert service._current_backoff_ms == 10  # noqa: SLF001
        ticks.advance(5)


# ---------------------------------------------------------------------------
# Flapping link (is_linked bounces)
# ---------------------------------------------------------------------------


def test_link_flap_up_between_check_and_handle_stays_connected() -> None:
    """A link that reads down at check() but back up by handle() (a brief
    flap) does not force a reconnect — the service stays CONNECTED and fires
    no transition."""
    transitions = []
    service, ticks, adapter = _service()
    service.on_state_change(lambda old, new: transitions.append((old, new)))
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())  # CONNECTED
    transitions.clear()

    adapter.drop_link()
    assert service.check(ticks.ticks_ms()) is True  # check() sees the blip
    adapter.restore_link()  # link bounced back before handle() ran
    service.handle(ticks.ticks_ms())  # is_linked() True again -> no-op

    assert service.state == WifiState.CONNECTED
    assert transitions == []


def test_link_flapping_during_reconnecting_still_settles() -> None:
    """A link bouncing up and down while RECONNECTING doesn't wedge the
    service: it keeps attempting on its backoff schedule and settles
    CONNECTED once an attempt succeeds."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())  # CONNECTED

    adapter.set_connect_outcomes([False, False, True])
    adapter.drop_link()
    service.handle(ticks.ticks_ms())  # RECONNECTING

    service.handle(ticks.ticks_ms())  # attempt: False
    adapter.restore_link()            # link flaps up on its own
    ticks.advance(10)
    service.handle(ticks.ticks_ms())  # attempt: False (flaps back down)
    adapter.restore_link()            # flaps up again
    ticks.advance(20)
    service.handle(ticks.ticks_ms())  # attempt: True -> CONNECTED

    assert service.state == WifiState.CONNECTED


# ---------------------------------------------------------------------------
# connect() raising mid-reconnect
# ---------------------------------------------------------------------------


def test_connect_raising_mid_reconnect_backs_off_then_recovers() -> None:
    """A connect() that raises during RECONNECTING is a settled failure:
    the service records last_error, backs off, stays RECONNECTING (with the
    default unlimited retries), and recovers when the fault clears."""
    service, ticks, adapter = _service()
    adapter.set_connect_outcome(True)
    service.handle(ticks.ticks_ms())  # CONNECTED

    adapter.drop_link()
    service.handle(ticks.ticks_ms())  # RECONNECTING

    adapter.set_connect_outcome(_DropError)
    service.handle(ticks.ticks_ms())  # attempt raises -> attempts=1, backoff
    assert service.state == WifiState.RECONNECTING
    assert isinstance(service.last_error, _DropError)
    assert service._reconnect_attempts == 1  # noqa: SLF001

    ticks.advance(10)
    service.handle(ticks.ticks_ms())  # raises again -> attempts=2
    assert service.state == WifiState.RECONNECTING
    assert service._reconnect_attempts == 2  # noqa: SLF001

    adapter.set_connect_outcome(True)
    ticks.advance(20)
    service.handle(ticks.ticks_ms())  # recovers -> CONNECTED
    assert service.state == WifiState.CONNECTED
    assert service.last_error is None


def test_connect_raise_on_nonblocking_adapter_is_settled_failure() -> None:
    """A raising connect() on a NON-blocking substrate must count a settled
    failure and back off, not arm the in-flight poll window.

    Regression guard: the in-flight path exists for a dispatched join still
    associating; a raised connect() dispatched nothing, so waiting out
    connect_timeout_ms polling a dead link would stall the retry loop.
    """
    service, ticks, adapter = _service()
    adapter.set_connect_blocks(False)  # model the MicroPython substrate
    adapter.set_connect_outcome(_DropError)

    service.handle(ticks.ticks_ms())  # CONNECTING attempt raises

    assert service._attempt_deadline_ms is None  # noqa: SLF001 - NOT in-flight
    assert service._reconnect_attempts == 1  # noqa: SLF001 - counted as failure
    assert isinstance(service.last_error, _DropError)
    assert service.state == WifiState.CONNECTING  # reconnect_max None -> keeps trying


# ---------------------------------------------------------------------------
# Non-blocking in-flight association driven through check()/handle()
# ---------------------------------------------------------------------------


def test_nonblocking_association_polled_through_check_handle() -> None:
    """A non-blocking join that links after several polls reaches CONNECTED
    via the runner's check()/handle() cycle, dispatching connect() once.

    Exercises the in-flight branch of check() (returns True every tick while
    an association is pending) that the handle()-only adapter tests miss.
    """
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    fake.set_deferred_link(link_after=3)

    fake.tick()  # DISCONNECTED -> CONNECTING, dispatch join, arm in-flight
    assert fake.state == WifiState.CONNECTING
    # While the association is in flight, check() must keep asking for ticks.
    assert fake.check(ticks.ticks_ms()) is True

    for _ in range(5):
        fake.tick()
        if fake.state == WifiState.CONNECTED:
            break
    assert fake.state == WifiState.CONNECTED
    assert [entry[0] for entry in fake.calls].count("connect") == 1


# ---------------------------------------------------------------------------
# FAILED-exhaustion semantics
# ---------------------------------------------------------------------------


def test_default_unlimited_reconnect_never_enters_failed() -> None:
    """With reconnect_max=None (the default, the unattended-device setting),
    the service never gives up: it keeps retrying with capped backoff and
    never reaches the terminal FAILED state, however long the AP is gone."""
    service, ticks, adapter = _service(
        config_overrides={
            "reconnect_backoff_start_ms": 10,
            "reconnect_backoff_max_ms": 40,
        },
    )
    adapter.set_connect_outcome(False)

    for _ in range(50):
        service.handle(ticks.ticks_ms())
        ticks.advance(100)

    assert service.state != WifiState.FAILED
    assert service.check(ticks.ticks_ms()) is True  # still has work to do
    assert service._reconnect_attempts >= 40  # noqa: SLF001 - kept trying
    assert service._current_backoff_ms == 40  # noqa: SLF001 - backoff capped


def test_reconnect_max_counts_initial_connect_attempts_to_failed() -> None:
    """reconnect_max bounds the initial connect too (not just post-CONNECTED
    reconnects): three refused attempts from boot exhaust a cap of 3 and
    land in the terminal FAILED state — the power-restore race."""
    service, ticks, adapter = _service(config_overrides={"reconnect_max": 3})
    adapter.set_connect_outcome(False)

    service.handle(ticks.ticks_ms())  # attempt 1
    ticks.advance(200)
    assert service.state == WifiState.CONNECTING
    service.handle(ticks.ticks_ms())  # attempt 2
    ticks.advance(200)
    assert service.state == WifiState.CONNECTING
    service.handle(ticks.ticks_ms())  # attempt 3 -> exhausted
    assert service.state == WifiState.FAILED


# ---------------------------------------------------------------------------
# Raising state callback is isolated
# ---------------------------------------------------------------------------


def test_raising_callback_is_isolated_and_recorded() -> None:
    """A callback that raises can't abort later callbacks or escape into the
    runner tick: the error is stored in ``last_error`` and the rest fire."""

    class _CallbackBoom(Exception):
        pass

    seen = []
    service, ticks, adapter = _service()

    def _boom(_old, _new):
        raise _CallbackBoom("callback blew up")

    service.on_state_change(_boom)
    service.on_state_change(lambda _o, _n: seen.append("after"))
    adapter.set_connect_outcome(True)

    service.handle(ticks.ticks_ms())  # transitions still complete

    assert service.state == WifiState.CONNECTED
    assert seen == ["after", "after"]  # 2 transitions, later callback each time
    assert isinstance(service.last_error, _CallbackBoom)


# ---------------------------------------------------------------------------
# FakeWifiAdapter / FakeWifi test hooks these scenarios rely on
# ---------------------------------------------------------------------------


def test_fake_adapter_restore_link_relinks_without_connect() -> None:
    """``restore_link`` flips ``is_linked`` back to True (an AP that returned
    on its own), the complement to ``drop_link``."""
    adapter = FakeWifiAdapter()
    adapter.connect(WifiConfig(ssid="x", password="y"))
    adapter.drop_link()
    assert adapter.is_linked() is False
    adapter.restore_link()
    assert adapter.is_linked() is True


def test_fake_adapter_defaults_to_blocking_connect() -> None:
    """The fake models a blocking (CircuitPython-style) substrate by default."""
    adapter = FakeWifiAdapter()
    assert adapter.connect_blocks is True


def test_fake_adapter_set_connect_blocks_toggles_substrate_model() -> None:
    """``set_connect_blocks(False)`` switches to the non-blocking (MP) model."""
    adapter = FakeWifiAdapter()
    adapter.set_connect_blocks(False)
    assert adapter.connect_blocks is False


def test_fake_adapter_deferred_link_flips_after_polls() -> None:
    """``set_deferred_link`` models a non-blocking join: connect() dispatches
    and returns False, then is_linked() reports True on the Nth poll."""
    adapter = FakeWifiAdapter()
    adapter.set_deferred_link(link_after=2)
    assert adapter.connect_blocks is False
    assert adapter.connect(WifiConfig(ssid="x", password="y")) is False
    assert adapter.is_linked() is False  # poll 1
    assert adapter.is_linked() is True   # poll 2 -> linked


def test_fake_wifi_wrapper_exposes_restore_and_block_hooks() -> None:
    """The FakeWifi wrapper forwards ``set_connect_blocks`` / ``restore_link``
    so a drop-then-return cycle drives through the ergonomic surface."""
    ticks = FakeTicks()
    fake = FakeWifi(ticks)
    fake.set_connect_blocks(True)  # explicit blocking model via the wrapper
    fake.set_connect_outcome(True)
    fake.tick()
    assert fake.state == WifiState.CONNECTED

    fake.drop_link()
    assert fake.adapter.is_linked() is False
    fake.restore_link()
    assert fake.adapter.is_linked() is True
