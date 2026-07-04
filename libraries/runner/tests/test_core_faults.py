"""Argument validation, add() error cases, and handler-fault isolation.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""


from chumicro_runner import ReentrantTickError, Runner
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- Runner: error cases --


def test_add_no_args_raises() -> None:
    """add() with no task and no handler should raise ValueError."""
    fake = FakeTicks()
    runner = Runner(ticks=fake)

    with raises(ValueError):
        runner.add()


# -- Runner: handler fault isolation --


def test_faulting_handler_is_isolated_and_siblings_still_fire() -> None:
    """A faulting handler is counted and a sibling gated the same tick still fires."""
    runner = Runner(ticks=FakeTicks())
    fired = []

    def boom(now_ms: int) -> None:
        raise ValueError("handler fault")

    def good(now_ms: int) -> None:
        fired.append(now_ms)

    runner.add(handler=boom)
    runner.add(handler=good)

    now_ms = runner.tick()

    assert fired == [now_ms]
    assert runner.handler_errors == 1


def test_pending_cleared_so_isolated_fault_does_not_re_fire() -> None:
    """A handler faulting every tick leaves _pending empty, so a sibling fires once per tick."""
    runner = Runner(ticks=FakeTicks())
    good_calls = []

    def boom(now_ms: int) -> None:
        raise ValueError("fault every tick")

    def good(now_ms: int) -> None:
        good_calls.append(now_ms)

    runner.add(handler=boom)
    runner.add(handler=good)

    runner.tick()
    runner.tick()
    runner.tick()

    assert len(good_calls) == 3
    assert runner.handler_errors == 3
    assert runner._pending == []


def test_on_handler_error_hook_receives_the_handle_and_exception() -> None:
    """The on_handler_error callback receives the faulting task's handle and the exception."""
    seen = []

    def on_error(handle: object, error: BaseException) -> None:
        seen.append((handle, error))

    runner = Runner(ticks=FakeTicks(), on_handler_error=on_error)

    def boom(now_ms: int) -> None:
        raise ValueError("reported")

    handle = runner.add(handler=boom)
    runner.tick()

    assert len(seen) == 1
    reported_handle, reported_error = seen[0]
    assert reported_handle is handle
    assert isinstance(reported_error, ValueError)


def test_on_handler_error_hook_that_raises_is_itself_isolated() -> None:
    """A callback that raises is swallowed and counted, not re-breaking the loop."""
    def on_error(handle: object, error: BaseException) -> None:
        raise RuntimeError("buggy hook")

    runner = Runner(ticks=FakeTicks(), on_handler_error=on_error)

    def boom(now_ms: int) -> None:
        raise ValueError("handler fault")

    runner.add(handler=boom)
    runner.tick()

    assert runner.handler_errors == 2


def test_run_count_task_that_faults_still_auto_removes() -> None:
    """A run_count=1 handler that raises fires once, is counted, then auto-removes."""
    runner = Runner(ticks=FakeTicks())
    calls = []

    def boom(now_ms: int) -> None:
        calls.append(now_ms)
        raise ValueError("boom")

    handle = runner.add(handler=boom, run_count=1)

    runner.tick()
    runner.tick()

    assert len(calls) == 1
    assert handle.active is False
    assert runner.handler_errors == 1


def test_base_exception_from_handler_propagates_and_is_not_counted() -> None:
    """KeyboardInterrupt propagates out of tick() and does not bump handler_errors."""
    runner = Runner(ticks=FakeTicks())

    def interrupt(now_ms: int) -> None:
        raise KeyboardInterrupt

    runner.add(handler=interrupt)

    propagated = False
    try:
        runner.tick()
    except KeyboardInterrupt:
        propagated = True

    assert propagated is True
    assert runner.handler_errors == 0


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


def test_reentrant_tick_from_handler_propagates() -> None:
    """A re-entrant tick() raises ReentrantTickError and is not counted as a handler fault."""
    runner = Runner(ticks=FakeTicks())

    def reenter(now_ms: int) -> None:
        runner.tick()

    handle = runner.add(handler=reenter)

    with raises(ReentrantTickError):
        runner.tick()

    # Framework misuse propagates rather than bumping the handler-fault count.
    assert runner.handler_errors == 0
    # The outer tick's finally cleared the guard, so the runner is not wedged
    # once the offending handler is removed.
    handle.remove()
    runner.tick()


def test_ticking_flag_resets_after_handler_fault() -> None:
    """An isolated handler fault still clears the re-entrancy guard, so the next tick runs."""
    runner = Runner(ticks=FakeTicks())

    def boom(now_ms: int) -> None:
        raise ValueError("boom")

    runner.add(handler=boom)
    runner.tick()
    runner.tick()  # would raise RuntimeError if _ticking stayed True

    assert runner.handler_errors == 2
