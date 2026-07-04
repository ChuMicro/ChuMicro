"""``Runner.wait`` edge branches (dispatcher, poll-set sync resilience,
timeout computation), add_periodic validation, and ``run_until``.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""


import select

from _core_helpers import _IOService, _IOServiceWithErrorHook
from chumicro_runner import Runner
from chumicro_runner.testing import FakePoller
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- Runner.wait: dispatcher branches --


def test_wait_io_error_skips_handler_only_entries() -> None:
    """A POLLERR dispatch must not crash when handler-only entries
    (no service) sit alongside the io-service whose socket faulted.
    """
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    runner.add(handler=lambda now_ms: None)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLERR)
    runner.wait(0)

    assert service.io_error_calls == [(0, select.POLLERR)]


def test_wait_io_error_skips_services_with_io_socket_none() -> None:
    """A service whose io_socket is None at dispatch time is skipped, not
    crashed on.  The faulted-socket service still receives io_error.
    """
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    # Decoy service: registered as a service but its io_socket is None.
    decoy = _IOService(sock=None)
    runner.add(decoy, period_ms=100)
    target = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(target, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLHUP)
    runner.wait(0)

    assert target.io_error_calls == [(0, select.POLLHUP)]


def test_wait_io_error_for_unknown_socket_is_silent() -> None:
    """A POLLERR for an obj that matches no registered service exits the
    dispatcher cleanly — the loop walks every entry and returns without
    raising.  Models a stale poll registration we haven't observed yet.
    """
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(object(), select.POLLERR)  # different obj
    runner.wait(0)

    assert service.io_error_calls == []


# -- Runner.wait: poll-set sync resilience --


def test_wait_swallows_keyerror_from_unregister() -> None:
    """A poller whose unregister raises KeyError (poll-set divergence —
    socket already closed at the OS level) must not crash wait().  The
    runner's registered_interest dict is the source of truth and stays
    consistent.
    """
    class _KeyErrorPoller(FakePoller):
        def unregister(self, obj: object) -> None:
            super().unregister(obj)
            raise KeyError(obj)

    poller = _KeyErrorPoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)
    assert id(sock) in runner._registered_interest

    service.io_socket = None
    runner.wait(0)  # must not raise

    assert id(sock) not in runner._registered_interest


def test_wait_swallows_oserror_from_unregister() -> None:
    """Same posture as KeyError — OSError from the OS-level poller (fd
    closed underneath us) is swallowed."""
    class _OSErrorPoller(FakePoller):
        def unregister(self, obj: object) -> None:
            super().unregister(obj)
            raise OSError("bad fd")

    poller = _OSErrorPoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    service.io_socket = None
    runner.wait(0)  # must not raise

    assert id(sock) not in runner._registered_interest


# -- Runner.wait: _compute_timeout edge branches --


def test_wait_timeout_first_entry_wins_when_second_is_later() -> None:
    """Two entries with different deadlines — second entry's larger delta
    does not displace the smaller nearest already accumulated.
    """
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=50)         # nearer deadline
    runner.add_periodic(lambda now_ms: None, period_ms=500)  # farther

    runner.wait(0)

    assert poller.ipoll_calls == [50]


def test_wait_ignores_service_returning_none_from_next_deadline() -> None:
    """A service whose next_deadline returns None contributes no
    timeout shrinkage — the nearest next_due_ms wins."""

    class _SometimesNoDeadline(_IOService):
        def next_deadline(self, now_ms: int) -> int | None:
            return None

    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _SometimesNoDeadline(sock=sock, wants_read=True)
    runner.add(service, period_ms=80)

    runner.wait(0)

    assert poller.ipoll_calls == [80]


def test_wait_next_deadline_larger_than_nearest_does_not_replace_it() -> None:
    """A service's next_deadline farther out than the entry's next_due_ms
    must not replace the smaller nearest already set."""

    class _FarDeadline(_IOService):
        def next_deadline(self, now_ms: int) -> int:
            return now_ms + 500  # much later than the 25ms period

    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _FarDeadline(sock=sock, wants_read=True)
    runner.add(service, period_ms=25)

    runner.wait(0)

    assert poller.ipoll_calls == [25]


# -- add_periodic validation --


def test_add_periodic_period_ms_none_raises() -> None:
    """Explicitly passing period_ms=None to add_periodic is the
    one error path for the required-keyword guard."""
    runner = Runner(ticks=FakeTicks())

    with raises(ValueError):
        runner.add_periodic(lambda now_ms: None, period_ms=None)


# -- _sync_poll_set with default poller (still un-built) --
#
# When a service exposes an io_socket while the nearest deadline is
# already due, wait() returns early without lazy-building the default
# adapter.  The registered_interest dict still updates on every
# _sync_poll_set.  A subsequent wait with flipped io_wants_* exercises
# the modify and unregister branches while ``poller is None`` is still
# true.


def test_sync_modify_branch_when_default_poller_not_yet_built() -> None:
    """An io-service flapping read↔write across two waits whose deadline
    is already due updates the registered_interest dict without
    crashing, even though no poller has been built yet (a due deadline
    returns wait() before the lazy build)."""
    runner = Runner(ticks=FakeTicks())  # poller=None
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)  # next due at tick 100

    runner.wait(200)  # deadline already due; returns before the lazy build
    assert runner._poller is None
    slot = runner._registered_interest[id(sock)]
    assert slot[0] is sock and slot[1] == _select_pollin()

    service.wants_read = False
    service.wants_write = True
    runner.wait(200)  # modify branch with poller=None — no-op on poller, dict updates

    assert runner._poller is None
    slot = runner._registered_interest[id(sock)]
    assert slot[0] is sock and slot[1] == _select_pollout()


def test_sync_unregister_branch_when_default_poller_not_yet_built() -> None:
    """Releasing io_socket on a service registered without a built poller
    drops the dict entry without trying to unregister from a poller
    that does not exist."""
    runner = Runner(ticks=FakeTicks())  # poller=None
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)

    runner.wait(200)  # deadline already due; returns before the lazy build
    assert id(sock) in runner._registered_interest

    service.io_socket = None
    runner.wait(200)

    assert runner._poller is None
    assert id(sock) not in runner._registered_interest


def test_wait_parks_in_poller_when_only_socket_driven_services() -> None:
    """A socket-driven service with no deadline anywhere makes wait()
    block in ipoll with the infinite timeout (-1) instead of returning
    immediately and busy-spinning the tick loop."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service)  # no period_ms — no deadline source at all

    runner.wait(0)

    assert poller.ipoll_calls == [-1]


def test_wait_returns_when_no_sockets_and_no_deadline() -> None:
    """Handler-only entries contribute neither sockets nor deadlines, and
    nothing can wake a sleep — wait() returns instead of blocking."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    runner.add(handler=lambda now_ms: None)

    runner.wait(0)

    assert poller.ipoll_calls == []


def test_run_until_returns_true_when_predicate_becomes_truthy() -> None:
    """run_until ticks until the predicate is satisfied, driving handlers
    each tick, then returns True."""
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    fired = []
    runner.add(handler=lambda now_ms: fired.append(now_ms))

    result = runner.run_until(lambda: len(fired) >= 3)

    assert result is True
    assert len(fired) == 3


def test_run_until_returns_false_on_timeout() -> None:
    """A predicate that never fires returns False once the timeout budget
    elapses (a periodic task supplies the deadline that bounds wait())."""
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    # A periodic task both advances work and gives wait() a deadline.
    runner.add_periodic(lambda now_ms: None, period_ms=10)

    result = runner.run_until(lambda: False, timeout_ms=50)

    assert result is False


def test_run_until_handle_form_runs_generator_to_completion() -> None:
    """Passing a generator handle runs until it finishes and returns True."""
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    steps = []

    def flow():
        steps.append("a")
        yield
        steps.append("b")

    handle = runner.add_generator(flow())
    result = runner.run_until(handle)

    assert result is True
    assert steps == ["a", "b"]
    assert handle.done is True


def test_run_until_handle_form_reraises_task_death() -> None:
    """A handle whose task died re-raises handle.error from run_until,
    so a demo fails loudly instead of exiting clean."""
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)

    def dies():
        yield
        raise ValueError("task died")

    handle = runner.add_generator(dies())
    caught = None
    try:
        runner.run_until(handle)
    except ValueError as error:
        caught = error

    assert caught is handle.error
    assert handle.done is True


def test_run_until_bare_timeout_runs_for_the_window() -> None:
    """predicate=None with a timeout reads as "run for this long" — a
    drain window — and returns False at the deadline."""
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    runner.add_periodic(lambda now_ms: None, period_ms=10)

    assert runner.run_until(timeout_ms=50) is False


def test_wait_socketless_advances_fake_clock_via_injected_sleep_ms() -> None:
    """wait() with no socket and a FakeTicks delegates the idle sleep to
    the tick source: FakeTicks.sleep_ms advances ticks_ms by the
    computed timeout instead of sleeping for real, so the next tick sees
    the periodic task due."""
    fake = FakeTicks(start_ms=0)
    runner = Runner(ticks=fake)  # no poller, no socket
    fired: list[int] = []
    runner.add(handler=lambda now_ms: fired.append(now_ms), period_ms=100)

    # Timeout is the period (100 ms); no socket registered, so wait
    # sleeps it through FakeTicks.sleep_ms, advancing the fake clock.
    runner.wait(fake.ticks_ms())

    assert fake.ticks_ms() == 100
    assert fired == []  # wait sleeps, it does not dispatch
    runner.tick()  # now the 100 ms task is due
    assert fired == [100]


def test_wait_uses_module_sleep_when_tick_source_lacks_sleep_ms() -> None:
    """A tick source without sleep_ms falls back to the module _sleep_ms;
    the cached sleeper is the module helper, not a bound FakeTicks
    method."""
    from chumicro_runner import core as runner_core

    class _NoSleepTicks:
        def __init__(self) -> None:
            self._now = 0

        def ticks_ms(self) -> int:
            return self._now

        def ticks_diff(self, end: int, start: int) -> int:
            return end - start

        def ticks_add(self, ticks_val: int, delta: int) -> int:
            return ticks_val + delta

    runner = Runner(ticks=_NoSleepTicks())
    assert runner._sleep_ms is runner_core._sleep_ms


def _select_pollin() -> int:
    return select.POLLIN


def _select_pollout() -> int:
    return select.POLLOUT
