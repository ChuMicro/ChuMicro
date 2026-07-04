"""TaskHandle lifecycle, the task registration shapes, and CallRecorder.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""


from _core_helpers import _GateTask
from chumicro_runner import Runner, TaskHandle
from chumicro_runner.testing import CallRecorder
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

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


def test_task_plus_handler_is_rejected() -> None:
    """The separate check-plus-handler shape was removed: a task object
    and a handler in one registration is a ValueError, not a silent
    override."""
    runner = Runner(ticks=FakeTicks())
    with raises(ValueError):
        runner.add(_GateTask(should_fire=True), handler=lambda now: None)
    with raises(ValueError):
        runner.add(lambda now: True, handler=lambda now: None)


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


# -- Mixed patterns --


def test_all_patterns_together() -> None:
    """Object-based, callable-based, handler-only, and periodic all in one runner."""
    fake = FakeTicks()
    results = []

    svc = _GateTask(should_fire=True)

    runner = Runner(ticks=fake)
    runner.add(svc)  # object-based
    runner.add(handler=lambda now: results.append("handler-only"))
    runner.add_periodic(lambda now: results.append("periodic"), period_ms=100)

    fake.advance(100)
    runner.tick()

    assert svc.handle_count == 1
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
