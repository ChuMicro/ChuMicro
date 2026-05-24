"""Tests for the core runner-pattern abstractions.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""

import select

from chumicro_runner import Runner, TaskHandle
from chumicro_runner.testing import CallRecorder, FakePoller
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- Helpers --


class _GateTask:
    """Minimal gate-based task component for testing."""

    def __init__(self, should_fire: bool = True) -> None:
        """Create a stub that returns *should_fire* from check()."""
        self.should_fire = should_fire
        self.check_count = 0
        self.handle_count = 0

    def check(self, now_ms: int) -> bool:
        """Return whether the handler should fire."""
        self.check_count += 1
        return self.should_fire

    def handle(self, now_ms: int) -> None:
        """Record that the handler was called."""
        self.handle_count += 1


# -- TaskHandle --


def test_add_returns_task_handle() -> None:
    """add() should return a TaskHandle."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())

    assert isinstance(handle, TaskHandle)


def test_task_handle_active_when_added() -> None:
    """TaskHandle should report active when first added."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())

    assert handle.active is True


def test_task_handle_period_ms_none_by_default() -> None:
    """period_ms should be None when no period is configured."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())

    assert handle.period_ms is None


def test_task_handle_period_ms_when_set() -> None:
    """period_ms should reflect the configured period."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask(), period_ms=200)

    assert handle.period_ms == 200


def test_task_handle_set_period_adds() -> None:
    """set_period() should add a period to a previously non-periodic task."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())

    assert handle.period_ms is None
    handle.set_period(300)
    assert handle.period_ms == 300


def test_task_handle_set_period_changes() -> None:
    """set_period() should replace the existing period."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask(), period_ms=100)

    handle.set_period(500)
    assert handle.period_ms == 500


def test_task_handle_set_period_none_removes() -> None:
    """set_period(None) should remove the period (task runs every tick)."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask(), period_ms=100)

    handle.set_period(None)
    assert handle.period_ms is None


def test_task_handle_remove() -> None:
    """remove() should deactivate the handle."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())
    handle.remove()

    assert handle.active is False


def test_task_handle_remove_idempotent() -> None:
    """Calling remove() twice should not raise."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())
    handle.remove()
    handle.remove()  # should not raise
    assert handle.active is False


def test_task_handle_repr() -> None:
    """TaskHandle repr should include period and status."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask(), period_ms=100)

    result = repr(handle)
    assert "100" in result
    assert "active" in result


def test_task_handle_repr_after_remove() -> None:
    """TaskHandle repr should show removed after remove()."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(_GateTask())
    handle.remove()

    assert "removed" in repr(handle)


# -- Runner: object-based (task with .check() and .handle()) --


def test_object_task_fires_handler_when_true() -> None:
    """Object-based task should fire .handle() when .check() returns True."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc)

    fake.advance(10)
    runner.tick()

    assert svc.check_count == 1
    assert svc.handle_count == 1


def test_object_task_skips_handler_when_false() -> None:
    """Object-based task should not fire .handle() when .check() returns False."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=False)

    runner = Runner(ticks=fake)
    runner.add(svc)

    runner.tick()

    assert svc.check_count == 1
    assert svc.handle_count == 0


def test_object_task_with_period() -> None:
    """Object-based task with period should only be checked when due."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc, period_ms=100)

    # Not due yet.
    runner.tick()
    assert svc.check_count == 0

    # Now due.
    fake.advance(100)
    runner.tick()
    assert svc.check_count == 1
    assert svc.handle_count == 1


def test_object_task_handler_override() -> None:
    """Passing handler= with an object should override .handle()."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)
    received = []

    runner = Runner(ticks=fake)
    runner.add(svc, handler=lambda now: received.append(now))

    fake.advance(5)
    runner.tick()

    # Custom handler was called, not .handle().
    assert received == [5]
    assert svc.handle_count == 0
    assert svc.check_count == 1


# -- Runner: callable-based (check_function + handler) --


def test_callable_check_gates_handler() -> None:
    """Callable check_function should gate handler_function."""
    fake = FakeTicks()
    received = []
    gate_open = [True]

    runner = Runner(ticks=fake)
    runner.add(
        lambda now: gate_open[0],
        handler=lambda now: received.append(now),
    )

    fake.advance(10)
    runner.tick()
    assert received == [10]

    # Close the gate.
    gate_open[0] = False
    received.clear()
    fake.advance(10)
    runner.tick()
    assert received == []


def test_callable_check_with_period() -> None:
    """Callable check with period should only be checked when due."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(
        lambda now: True,
        handler=lambda now: received.append(now),
        period_ms=100,
    )

    runner.tick()
    assert received == []

    fake.advance(100)
    runner.tick()
    assert received == [100]


# -- Runner: handler-only (no check) --


def test_handler_only_fires_every_tick() -> None:
    """Handler-only registration should fire every tick."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now))

    runner.tick()
    assert received == [0]

    fake.advance(10)
    runner.tick()
    assert received == [0, 10]


def test_handler_only_with_period() -> None:
    """Handler-only with period should fire per period."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), period_ms=100)

    runner.tick()
    assert received == []

    fake.advance(100)
    runner.tick()
    assert received == [100]


# -- Runner: add_periodic --


def test_periodic_fires_on_schedule() -> None:
    """Periodic handler should fire when the period elapses."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=100)

    runner.tick()
    assert received == []

    fake.advance(100)
    runner.tick()
    assert received == [100]


def test_periodic_repeats() -> None:
    """Periodic handler should fire repeatedly."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=50)

    fake.advance(50)
    runner.tick()
    assert len(received) == 1

    fake.advance(50)
    runner.tick()
    assert len(received) == 2


def test_periodic_set_period_changes_rate() -> None:
    """Changing period at runtime should take effect."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    handle = runner.add_periodic(lambda now: received.append(now), period_ms=100)

    fake.advance(100)
    runner.tick()
    assert len(received) == 1

    handle.set_period(50)
    fake.advance(50)
    runner.tick()
    assert len(received) == 2


def test_periodic_remove() -> None:
    """Removed periodic handler should no longer fire."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    handle = runner.add_periodic(lambda now: received.append(1), period_ms=50)

    fake.advance(50)
    runner.tick()
    assert len(received) == 1

    handle.remove()
    fake.advance(50)
    runner.tick()
    assert len(received) == 1


def test_periodic_handler_receives_now_ms() -> None:
    """Periodic handler should receive the shared now_ms timestamp."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=100)

    fake.advance(100)
    runner.tick()

    assert received == [100]


# -- Runner: batch firing and ordering --


def test_handlers_fire_in_batch() -> None:
    """All handlers should fire after all checks are done."""
    fake = FakeTicks()
    order = []

    class _OrderedGate:
        """Gate that records when it is checked."""

        def __init__(self, name: str) -> None:
            """Create a gate with the given name."""
            self._name = name

        def check(self, now_ms: int) -> bool:
            """Record the check and return True."""
            order.append(f"check:{self._name}")
            return True

        def handle(self, now_ms: int) -> None:
            """Record the handle call."""
            order.append(f"fire:{self._name}")

    runner = Runner(ticks=fake)
    runner.add(_OrderedGate("a"))
    runner.add(_OrderedGate("b"))

    runner.tick()

    assert order == ["check:a", "check:b", "fire:a", "fire:b"]


# -- Runner: shared timestamps --


def test_runner_returns_shared_timestamp() -> None:
    """tick() should return the captured now_ms."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    fake.advance(42)
    assert runner.tick() == 42


def test_runner_passes_same_timestamp_to_all() -> None:
    """All tasks should receive the same now_ms on a single tick."""
    fake = FakeTicks()
    timestamps = []

    class _Recorder:
        """Record each now_ms received."""

        def check(self, now_ms: int) -> bool:
            """Append now_ms to the shared list."""
            timestamps.append(now_ms)
            return False

    runner = Runner(ticks=fake)
    runner.add(_Recorder(), handler=lambda now: None)
    runner.add(_Recorder(), handler=lambda now: None)
    runner.add(_Recorder(), handler=lambda now: None)

    fake.advance(77)
    runner.tick()

    assert timestamps == [77, 77, 77]


def test_runner_defaults_to_real_ticks() -> None:
    """Runner with no ticks argument should use chumicro_timing.ticks_ms."""
    runner = Runner()

    now = runner.tick()

    assert isinstance(now, int)
    assert now >= 0


# -- Runner: period gating --


def test_period_gates_check() -> None:
    """Task with period should only be called when the period elapses."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc, period_ms=100)

    runner.tick()
    assert svc.check_count == 0

    fake.advance(100)
    runner.tick()
    assert svc.check_count == 1


def test_period_does_not_fire_early() -> None:
    """Task should not be called before the period elapses."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc, period_ms=100)

    fake.advance(99)
    runner.tick()

    assert svc.check_count == 0


def test_period_repeats() -> None:
    """Period gate should fire again after another period elapses."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc, period_ms=100)

    fake.advance(100)
    runner.tick()
    assert svc.handle_count == 1

    fake.advance(100)
    runner.tick()
    assert svc.handle_count == 2


def test_multiple_periods() -> None:
    """Multiple tasks with different periods should fire independently."""
    fake = FakeTicks()
    fast_received = []
    slow_received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(lambda now: fast_received.append(1), period_ms=50)
    runner.add_periodic(lambda now: slow_received.append(1), period_ms=200)

    # At 50ms: fast fires, slow does not.
    fake.advance(50)
    runner.tick()
    assert len(fast_received) == 1
    assert len(slow_received) == 0

    # At 100ms: fast fires again, slow still not.
    fake.advance(50)
    runner.tick()
    assert len(fast_received) == 2
    assert len(slow_received) == 0

    # At 200ms: both fire.
    fake.advance(100)
    runner.tick()
    assert len(fast_received) == 3
    assert len(slow_received) == 1


def test_period_and_no_period_together() -> None:
    """Both periodic and every-tick tasks should work together."""
    fake = FakeTicks()
    always = _GateTask(should_fire=True)
    periodic_received = []

    runner = Runner(ticks=fake)
    runner.add(always)
    runner.add_periodic(lambda now: periodic_received.append(1), period_ms=100)

    # Tick 0: always fires, periodic not due.
    runner.tick()
    assert always.handle_count == 1
    assert len(periodic_received) == 0

    # Advance past period: both fire.
    fake.advance(100)
    runner.tick()
    assert always.handle_count == 2
    assert len(periodic_received) == 1


# -- Runner: runtime mutation --


def test_remove_stops_task() -> None:
    """Removed task should no longer be called."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    handle = runner.add(svc)

    runner.tick()
    assert svc.check_count == 1

    handle.remove()
    runner.tick()
    assert svc.check_count == 1


def test_set_period_at_runtime() -> None:
    """Adding a period at runtime should take effect."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    handle = runner.add(svc)

    # Runs every tick.
    runner.tick()
    assert svc.check_count == 1

    # Add a period.  The task stops firing until the period elapses.
    handle.set_period(200)
    runner.tick()
    assert svc.check_count == 1

    fake.advance(200)
    runner.tick()
    assert svc.check_count == 2


def test_remove_period_at_runtime() -> None:
    """Removing a period should make the task run every tick again."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    handle = runner.add(svc, period_ms=100)

    runner.tick()
    assert svc.check_count == 0

    handle.set_period(None)
    runner.tick()
    assert svc.check_count == 1


# -- Runner: error cases --


def test_add_no_args_raises() -> None:
    """add() with no task and no handler should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add()


# -- Mixed patterns --


def test_all_patterns_together() -> None:
    """Object-based, callable-based, handler-only, and periodic all in one runner."""
    fake = FakeTicks()
    results = []

    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc)  # object-based
    runner.add(lambda now: True, handler=lambda now: results.append("callable"))
    runner.add(handler=lambda now: results.append("handler-only"))
    runner.add_periodic(lambda now: results.append("periodic"), period_ms=100)

    fake.advance(100)
    runner.tick()

    assert svc.handle_count == 1
    assert "callable" in results
    assert "handler-only" in results
    assert "periodic" in results


# -- CallRecorder --


def test_call_recorder_records_calls() -> None:
    """CallRecorder should record all invocations."""
    recorder = CallRecorder()
    recorder(10)
    recorder(20)

    assert recorder.calls == [10, 20]
    assert len(recorder) == 2


def test_call_recorder_clear() -> None:
    """CallRecorder.clear should discard all recorded calls."""
    recorder = CallRecorder()
    recorder(10)
    recorder.clear()

    assert len(recorder) == 0
    assert recorder.calls == []


def test_call_recorder_as_handler() -> None:
    """CallRecorder should work as a handler in Runner."""
    fake = FakeTicks()
    recorder = CallRecorder()

    runner = Runner(ticks=fake)
    runner.add_periodic(recorder, period_ms=100)

    runner.tick()
    assert len(recorder) == 0

    fake.advance(100)
    runner.tick()
    assert recorder.calls == [100]


# -- run_count --


def test_run_count_fires_exactly_n_times() -> None:
    """Handler with run_count should fire exactly N times then stop."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), run_count=3)

    for _i in range(5):
        fake.advance(10)
        runner.tick()

    assert len(received) == 3


def test_run_count_auto_removes() -> None:
    """Task should be inactive after run_count is exhausted."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None, run_count=1)

    runner.tick()
    assert handle.active is False


def test_run_count_with_period() -> None:
    """Periodic task with run_count should fire N periods then stop."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now), period_ms=100, run_count=2,
    )

    # Period 1.
    fake.advance(100)
    runner.tick()
    assert len(received) == 1

    # Period 2.
    fake.advance(100)
    runner.tick()
    assert len(received) == 2

    # Period 3: should not fire.
    fake.advance(100)
    runner.tick()
    assert len(received) == 2


def test_run_count_one_is_one_shot() -> None:
    """run_count=1 should fire exactly once."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now), period_ms=50, run_count=1,
    )

    fake.advance(50)
    runner.tick()
    assert received == [50]

    fake.advance(50)
    runner.tick()
    assert received == [50]


def test_run_count_property() -> None:
    """TaskHandle.run_count should reflect remaining count."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None, run_count=3)

    assert handle.run_count == 3

    runner.tick()
    assert handle.run_count == 2

    runner.tick()
    assert handle.run_count == 1


def test_run_count_none_by_default() -> None:
    """run_count should be None when not specified."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None)

    assert handle.run_count is None


def test_run_count_zero_raises() -> None:
    """run_count=0 should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add(handler=lambda now: None, run_count=0)


def test_run_count_zero_raises_periodic() -> None:
    """run_count=0 on add_periodic should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add_periodic(lambda now: None, period_ms=100, run_count=0)


def test_run_count_repr() -> None:
    """TaskHandle repr should include run_count when set."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None, run_count=5)

    result = repr(handle)
    assert "run_count=5" in result


# -- start_after_ms --


def test_start_after_ms_delays_handler() -> None:
    """Handler should not fire before start_after_ms elapses."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), start_after_ms=500)

    # Before delay.
    fake.advance(200)
    runner.tick()
    assert received == []

    fake.advance(200)
    runner.tick()
    assert received == []

    # At delay.
    fake.advance(100)
    runner.tick()
    assert received == [500]


def test_start_after_ms_then_every_tick() -> None:
    """Handler-only with start_after_ms should run every tick after delay."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), start_after_ms=100)

    runner.tick()
    assert received == []

    fake.advance(100)
    runner.tick()
    assert received == [100]

    # Now should fire every tick.
    fake.advance(10)
    runner.tick()
    assert len(received) == 2


def test_start_after_ms_with_period() -> None:
    """start_after_ms should delay first fire.  Subsequent fires use period_ms."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now),
        period_ms=100,
        start_after_ms=500,
    )

    # Before start delay.
    fake.advance(400)
    runner.tick()
    assert received == []

    # At start delay: first fire.
    fake.advance(100)
    runner.tick()
    assert received == [500]

    # One period later: second fire.
    fake.advance(100)
    runner.tick()
    assert received == [500, 600]


def test_start_after_ms_with_check() -> None:
    """Object-based task with start_after_ms should delay check calls."""
    fake = FakeTicks()
    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc, start_after_ms=200)

    # Before delay: check should not be called.
    fake.advance(100)
    runner.tick()
    assert svc.check_count == 0

    # After delay: check runs normally.
    fake.advance(100)
    runner.tick()
    assert svc.check_count == 1
    assert svc.handle_count == 1


def test_start_after_ms_zero_fires_immediately() -> None:
    """start_after_ms=0 should fire on the first tick."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add(handler=lambda now: received.append(now), start_after_ms=0)

    runner.tick()
    assert received == [0]


# -- Validation --


def test_period_ms_zero_raises() -> None:
    """period_ms=0 should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add(handler=lambda now: None, period_ms=0)


def test_period_ms_negative_raises() -> None:
    """Negative period_ms should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add(handler=lambda now: None, period_ms=-10)


def test_set_period_zero_raises() -> None:
    """set_period(0) should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add(handler=lambda now: None)

    with raises(ValueError):
        handle.set_period(0)


def test_periodic_zero_raises() -> None:
    """add_periodic with period_ms=0 should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add_periodic(lambda now: None, period_ms=0)


def test_tick_is_not_reentrant() -> None:
    """A handler calling tick() on the same runner raises RuntimeError."""
    runner = Runner(ticks=FakeTicks())

    def reenter(now_ms: int) -> None:
        runner.tick()

    runner.add(handler=reenter)
    with raises(RuntimeError):
        runner.tick()


def test_ticking_flag_resets_after_handler_exception() -> None:
    """A handler raising must not wedge the runner.  The try/finally clears the guard."""
    runner = Runner(ticks=FakeTicks())

    def boom(now_ms: int) -> None:
        raise ValueError("boom")

    runner.add(handler=boom)
    with raises(ValueError):
        runner.tick()
    # If _ticking were left True, this would raise RuntimeError instead
    # of the handler's ValueError.
    with raises(ValueError):
        runner.tick()


# -- Runner.wait --


class _IOService:
    """Stub I/O service exposing the duck-typed ``io_*`` attributes
    that ``Runner.wait`` reads each loop."""

    def __init__(self, sock: object | None = None,
                 wants_read: bool = False,
                 wants_write: bool = False) -> None:
        self.io_socket = sock
        self.io_wants_read = wants_read
        self.io_wants_write = wants_write
        self.check_returns = False
        self.handle_count = 0

    def check(self, now_ms: int) -> bool:
        return self.check_returns

    def handle(self, now_ms: int) -> None:
        self.handle_count += 1


def test_wait_is_noop_when_no_entries() -> None:
    """A runner with no tasks returns immediately and never touches the poller."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)

    runner.wait(0)

    assert poller.ipoll_calls == []
    assert poller.register_calls == []


def test_wait_default_poller_stays_unbuilt_when_no_socket() -> None:
    """A runner with only timer-based entries never lazy-builds the poller."""
    runner = Runner(ticks=FakeTicks())  # poller=None => lazy
    runner.add_periodic(lambda now_ms: None, period_ms=100)

    runner.wait(0)

    assert runner._poller is None


def test_wait_registers_service_socket() -> None:
    """A service exposing io_socket + io_wants_read registers with POLLIN."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)

    runner.wait(0)

    assert (sock, select.POLLIN) in poller.register_calls
    assert poller.ipoll_calls == [100]


def test_wait_combines_read_and_write_into_one_eventmask() -> None:
    """A service wanting both read and write registers with POLLIN | POLLOUT."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True, wants_write=True)
    runner.add(service, period_ms=100)

    runner.wait(0)

    expected = select.POLLIN | select.POLLOUT
    assert (sock, expected) in poller.register_calls


def test_wait_modifies_when_interest_changes() -> None:
    """Going from read-only to read+write fires modify, not a second register."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)
    poller.register_calls.clear()

    service.io_wants_write = True
    runner.wait(0)

    expected = select.POLLIN | select.POLLOUT
    assert (sock, expected) in poller.modify_calls
    assert poller.register_calls == []


def test_wait_idempotent_when_interest_unchanged() -> None:
    """A second wait() with the same io_* state touches the poller zero times."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)
    poller.register_calls.clear()
    poller.modify_calls.clear()
    poller.unregister_calls.clear()

    runner.wait(0)

    assert poller.register_calls == []
    assert poller.modify_calls == []
    assert poller.unregister_calls == []


def test_wait_unregisters_when_service_releases_socket() -> None:
    """A service that goes io_socket=None drops out of the poll set."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    service.io_socket = None
    runner.wait(0)

    assert sock in poller.unregister_calls


def test_wait_unregisters_when_service_drops_to_no_interest() -> None:
    """io_wants_read=False and io_wants_write=False unregisters even when io_socket is still set."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    service.io_wants_read = False
    runner.wait(0)

    assert sock in poller.unregister_calls


class _IOServiceWithErrorHook(_IOService):
    """``_IOService`` plus an ``io_error`` hook that records calls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.io_error_calls: list[tuple[int, int]] = []

    def io_error(self, now_ms: int, eventmask: int) -> None:
        self.io_error_calls.append((now_ms, eventmask))


def test_wait_dispatches_io_error_on_pollerr() -> None:
    """POLLERR on a registered socket fires the service's ``io_error`` hook."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)  # First wait registers the socket.

    # Now script a POLLERR event for the next wait.
    poller.set_ready(sock, select.POLLERR)
    runner.wait(0)

    assert service.io_error_calls == [(0, select.POLLERR)]


def test_wait_dispatches_io_error_on_pollhup() -> None:
    """POLLHUP on a registered socket fires the service's ``io_error`` hook."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLHUP)
    runner.wait(50)

    assert service.io_error_calls == [(50, select.POLLHUP)]


def test_wait_combined_pollin_pollerr_still_fires_io_error() -> None:
    """A combined POLLIN | POLLERR mask still triggers io_error.

    POLLIN alone is a wake signal only -- runner doesn't dispatch
    anything for it.  POLLERR on the SAME event has to surface so
    the service learns the socket faulted."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    combined = select.POLLIN | select.POLLERR
    poller.set_ready(sock, combined)
    runner.wait(0)

    assert service.io_error_calls == [(0, combined)]


def test_wait_pollin_only_does_not_fire_io_error() -> None:
    """Plain POLLIN (wake signal) doesn't fire io_error -- only error masks do."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOServiceWithErrorHook(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLIN)
    runner.wait(0)

    assert service.io_error_calls == []


def test_wait_pollerr_on_service_without_io_error_hook_is_silent() -> None:
    """A service that doesn't expose ``io_error`` is opted out -- runner
    doesn't crash, just skips it."""
    import select
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)  # no io_error.
    runner.add(service, period_ms=100)
    runner.wait(0)

    poller.set_ready(sock, select.POLLERR)
    runner.wait(0)  # Should not raise.

    # Sanity: the opted-out service didn't sprout an io_error attribute
    # along the way (would mean the runner stored something on it).
    assert not hasattr(service, "io_error")


def test_wait_timeout_uses_nearest_next_due_ms() -> None:
    """The wait timeout is the minimum across every entry's next_due_ms."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=500)
    runner.add_periodic(lambda now_ms: None, period_ms=80)

    runner.wait(0)

    assert poller.ipoll_calls == [80]


def test_wait_honors_next_deadline_hint() -> None:
    """A service exposing next_deadline(now_ms) shortens the timeout when its
    deadline is sooner than its next_due_ms."""

    class _ServiceWithDeadline(_IOService):
        def __init__(self, sock: object, deadline_ms: int) -> None:
            super().__init__(sock=sock, wants_read=True)
            self._deadline_ms = deadline_ms

        def next_deadline(self, now_ms: int) -> int:
            return now_ms + self._deadline_ms

    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _ServiceWithDeadline(sock, deadline_ms=25)
    runner.add(service, period_ms=500)

    runner.wait(0)

    assert poller.ipoll_calls == [25]


def test_wait_returns_immediately_when_deadline_already_passed() -> None:
    """A negative or zero timeout skips ipoll entirely."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()

    class _OverdueService(_IOService):
        def next_deadline(self, now_ms: int) -> int:
            return now_ms - 5  # already in the past

    service = _OverdueService(sock=sock, wants_read=True)
    runner.add(service)

    runner.wait(100)

    assert poller.ipoll_calls == []


def test_wait_drops_ipoll_iteration_result() -> None:
    """Whatever ipoll yields is discarded — check re-gates on the next tick."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service, period_ms=100)
    poller.set_ready(sock, select.POLLIN)

    runner.wait(0)

    assert service.handle_count == 0  # wait does not invoke handle()


def test_wait_callable_based_task_has_no_service_to_read() -> None:
    """A check + handler callable registration sets service=None on the handle
    so wait does not try to read io_* on a function."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    handle = runner.add(lambda now_ms: True, handler=lambda now_ms: None)

    assert handle.service is None
    runner.wait(0)  # must not raise

    assert poller.register_calls == []


def test_wait_handler_only_task_has_no_service() -> None:
    """A handler-only registration has no service to read io_* from."""
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    handle = runner.add(handler=lambda now_ms: None)

    assert handle.service is None
    runner.wait(0)

    assert poller.register_calls == []


# -- Runner.wait: dispatcher branches --


def test_wait_io_error_skips_callable_entries() -> None:
    """A POLLERR dispatch must not crash when callable-based entries
    (no service) sit alongside the io-service whose socket faulted.
    """
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    runner.add(lambda now_ms: True, handler=lambda now_ms: None)
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
# When a service exposes an io_socket but contributes no deadline
# (no period_ms, no next_deadline), _compute_timeout returns None and
# wait() returns early without lazy-building the default adapter.
# The registered_interest dict still updates on every _sync_poll_set.
# A subsequent wait with flipped io_wants_* exercises the modify and
# unregister branches while ``poller is None`` is still true.


def test_sync_modify_branch_when_default_poller_not_yet_built() -> None:
    """A no-period io-service flapping read↔write across two waits
    updates the registered_interest dict without crashing, even though
    no poller has been built yet (timeouts were both None so wait
    returned before the lazy build)."""
    runner = Runner(ticks=FakeTicks())  # poller=None
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service)  # no period_ms, no start_after_ms

    runner.wait(0)  # _sync registers in dict; timeout None; returns early
    assert runner._poller is None
    assert runner._registered_interest[id(sock)] == (sock, _select_pollin())

    service.io_wants_read = False
    service.io_wants_write = True
    runner.wait(0)  # modify branch with poller=None — no-op on poller, dict updates

    assert runner._poller is None
    assert runner._registered_interest[id(sock)] == (sock, _select_pollout())


def test_sync_unregister_branch_when_default_poller_not_yet_built() -> None:
    """Releasing io_socket on a service registered without a built poller
    drops the dict entry without trying to unregister from a poller
    that does not exist."""
    runner = Runner(ticks=FakeTicks())  # poller=None
    sock = object()
    service = _IOService(sock=sock, wants_read=True)
    runner.add(service)

    runner.wait(0)
    assert id(sock) in runner._registered_interest

    service.io_socket = None
    runner.wait(0)

    assert runner._poller is None
    assert id(sock) not in runner._registered_interest


def _select_pollin() -> int:
    return select.POLLIN


def _select_pollout() -> int:
    return select.POLLOUT
