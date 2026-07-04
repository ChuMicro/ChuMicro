"""Runner scheduling: periodic firing, batch dispatch, shared timestamps,
period gating, and runtime mutation of the schedule.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""


from _core_helpers import _GateTask
from chumicro_runner import Runner
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

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


def test_periodic_default_reanchors_from_the_late_tick() -> None:
    """A late tick pushes the default periodic's next fire late too: fired
    at 130 on a 100 ms period, it stays quiet at 200 and fires at 230."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(lambda now: received.append(now), period_ms=100)

    fake.advance(130)
    runner.tick()
    assert received == [130]

    fake.advance(70)
    runner.tick()
    assert received == [130]

    fake.advance(30)
    runner.tick()
    assert received == [130, 230]


def test_periodic_preserve_phase_holds_schedule_through_late_ticks() -> None:
    """With preserve_phase, a fire at 130 on a 100 ms period keeps the next
    deadline at 200, so the schedule does not inherit the tick's lateness."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now), period_ms=100, preserve_phase=True,
    )

    fake.advance(130)
    runner.tick()
    assert received == [130]

    fake.advance(70)
    runner.tick()
    assert received == [130, 200]


def test_periodic_preserve_phase_skips_missed_fires_without_burst() -> None:
    """A stall past several deadlines yields one fire, and the next deadline
    is the next future phase point (400), not a catch-up burst."""
    fake = FakeTicks()
    received = []

    runner = Runner(ticks=fake)
    runner.add_periodic(
        lambda now: received.append(now), period_ms=100, preserve_phase=True,
    )

    fake.advance(370)
    runner.tick()
    assert received == [370]

    runner.tick()
    assert received == [370]

    fake.advance(20)
    runner.tick()
    assert received == [370]

    fake.advance(10)
    runner.tick()
    assert received == [370, 400]


def test_preserve_phase_requires_period() -> None:
    """add() rejects preserve_phase on a registration with no period."""
    runner = Runner(ticks=FakeTicks())

    with raises(ValueError):
        runner.add(handler=lambda now: None, preserve_phase=True)


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

        def handle(self, now_ms: int) -> None:
            """Never fires — check always returns False."""

    runner = Runner(ticks=fake)
    runner.add(_Recorder())
    runner.add(_Recorder())
    runner.add(_Recorder())

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
