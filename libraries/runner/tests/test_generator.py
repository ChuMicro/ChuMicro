"""``Runner.add_generator`` + ``_GeneratorWrapper`` lifecycle.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Covers the lifecycle a sequential I/O
state machine actually walks — first yield primed at registration,
``StopIteration`` auto-removes the entry, ``cancel()`` fires the
generator's ``finally`` block, ``yield from`` delegation, and the
bare-yield / ready-wait protocol.  The wrapper's I/O surface (poll
interest + ``io_error`` dispatch) lives in the sibling
``test_generator_io.py``; both share ``_Sock`` / ``_Wait`` via
``_generator_helpers`` (split to keep each file's whole-file compile
under the CircuitPython unix-lane heap budget).
"""

import chumicro_runner
from _generator_helpers import _Sock, _Wait
from chumicro_runner import GeneratorHandle, Runner
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- Happy path: registration, run-to-completion, auto-removal --


def test_add_generator_returns_handle_with_done_false():
    runner = Runner(ticks=FakeTicks())

    def noop_gen():
        yield _Wait(until_ms=10)

    handle = runner.add_generator(noop_gen())
    assert isinstance(handle, GeneratorHandle)
    assert handle.done is False


def test_generator_advances_to_first_yield_at_registration():
    # The wrapper primes via .send(None) inside add_generator so the
    # first wait is visible to Runner.wait()'s _sync_poll_set on the
    # very first tick — without this, the loop sleeps on the wrong
    # deadline because the generator has not run yet.
    sock = _Sock()
    events = []

    def gen():
        events.append("before_yield")
        yield _Wait(sock=sock, want_read=True)
        events.append("after_yield")

    Runner(ticks=FakeTicks()).add_generator(gen())
    assert events == ["before_yield"]


def test_generator_runs_to_completion_across_ticks():
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    events = []

    def gen():
        events.append("start")
        yield _Wait(until_ms=10)
        events.append("after_sleep")
        yield _Wait(until_ms=20)
        events.append("done")

    handle = runner.add_generator(gen())
    assert events == ["start"]
    assert handle.done is False

    runner.tick()  # now_ms = 0; first sleep(10) not ready
    assert events == ["start"]
    assert handle.done is False

    ticks.advance(10)
    runner.tick()  # now_ms = 10; first sleep ready, gen advances
    assert events == ["start", "after_sleep"]
    assert handle.done is False

    ticks.advance(10)
    runner.tick()  # now_ms = 20; second sleep ready, gen returns
    assert events == ["start", "after_sleep", "done"]
    assert handle.done is True


def test_generator_finishing_during_start_marks_done_immediately():
    # A no-op generator that returns without yielding flips done True
    # the moment add_generator runs the prime .send(None).  The
    # consumer's while-not-done loop never enters the body — correct.
    def empty_gen():
        return
        yield  # unreachable; makes Python treat this as a generator function

    handle = Runner(ticks=FakeTicks()).add_generator(empty_gen())
    assert handle.done is True


def test_finished_generator_is_removed_from_runner_entries():
    runner = Runner(ticks=FakeTicks())

    def short_gen():
        yield _Wait(until_ms=0)  # ready immediately at now_ms=0

    handle = runner.add_generator(short_gen())
    assert len(runner._entries) == 1

    runner.tick()  # sleep ready at now_ms=0, gen returns, auto-removed.
    assert handle.done is True
    assert len(runner._entries) == 0


# -- Cancellation ----------------------------------------------------


def test_handle_error_records_generator_death():
    # M49: a body that raises mid-run leaves the exception on
    # handle.error, so a `while not handle.done` driver can report why
    # the task ended instead of discovering a silent death by timeout.
    def gen():
        yield
        raise ValueError("body died")

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(gen())
    assert handle.error is None

    runner.tick()  # resumes past the bare yield; the body raises

    assert handle.done is True
    assert isinstance(handle.error, ValueError)
    assert runner.handler_errors == 1


def test_handle_error_reaches_on_handler_error_hook():
    # The same death also fires the runner-level hook (the loud half of
    # M49) with the same exception instance the handle recorded.
    faults = []

    def gen():
        yield
        raise ValueError("body died")

    runner = Runner(
        ticks=FakeTicks(),
        on_handler_error=lambda handle, error: faults.append(error),
    )
    handle = runner.add_generator(gen())
    runner.tick()

    assert len(faults) == 1
    assert faults[0] is handle.error


def test_handle_error_stays_none_on_normal_return_and_cancel():
    def finishes():
        yield

    def runs_forever():
        while True:
            yield

    runner = Runner(ticks=FakeTicks())
    finished = runner.add_generator(finishes())
    runner.tick()
    assert finished.done is True and finished.error is None

    cancelled = runner.add_generator(runs_forever())
    cancelled.cancel()
    assert cancelled.done is True and cancelled.error is None


def test_cancel_fires_finally_block_in_generator():
    cleanup_ran = [False]

    def gen():
        try:
            yield _Wait(until_ms=10_000)  # would block forever
        finally:
            cleanup_ran[0] = True

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    assert cleanup_ran[0] is False

    handle.cancel()
    assert cleanup_ran[0] is True
    assert handle.done is True


def test_cancel_is_idempotent():
    def gen():
        yield _Wait(until_ms=10_000)

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    handle.cancel()
    handle.cancel()  # no error; second call is a no-op
    assert handle.done is True


def test_cancel_removes_entry_from_runner():
    runner = Runner(ticks=FakeTicks())

    def gen():
        yield _Wait(until_ms=10_000)

    handle = runner.add_generator(gen())
    assert len(runner._entries) == 1

    handle.cancel()
    assert len(runner._entries) == 0


def test_cancel_after_completion_is_a_noop():
    runner = Runner(ticks=FakeTicks())

    def gen():
        yield _Wait(until_ms=0)

    handle = runner.add_generator(gen())
    runner.tick()  # gen completes
    assert handle.done is True

    # Cancelling an already-done handle should not crash.
    handle.cancel()
    assert handle.done is True


# -- yield from delegation (the canonical use case) -----------------


def test_yield_from_delegation_works_across_helpers():
    # The whole point of the syntax choice: a helper that itself
    # yield-froms another helper composes naturally without an
    # async/await keyword cascade.
    events = []

    def inner_helper(label):
        events.append(f"inner:{label}:start")
        yield _Wait(until_ms=0)
        events.append(f"inner:{label}:done")

    def outer_gen():
        events.append("outer:start")
        yield from inner_helper("first")
        yield from inner_helper("second")
        events.append("outer:done")

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(outer_gen())

    while not handle.done:
        runner.tick()

    assert events == [
        "outer:start",
        "inner:first:start",
        "inner:first:done",
        "inner:second:start",
        "inner:second:done",
        "outer:done",
    ]


def test_yield_from_helper_return_value_is_received_by_caller():
    # PEP 380: ``return value`` from a generator carries through
    # ``yield from`` as the expression's value.  Socket-generator
    # helpers that return a connected sock rely on this — without it,
    # the caller has no path to receive the helper's terminal value.
    received = []

    def producer():
        yield _Wait(until_ms=0)
        return "produced-value"

    def consumer():
        result = yield from producer()
        received.append(result)

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(consumer())

    while not handle.done:
        runner.tick()

    assert received == ["produced-value"]


# -- bare yield + ready-wait protocol --------------------------------


def test_bare_yield_resumes_next_tick():
    """A bare ``yield`` suspends for exactly one tick — the generator
    resumes on the following tick and runs to completion instead of
    wedging with ``done`` stuck False."""
    runner = Runner(ticks=FakeTicks())
    progress = []

    def stepper():
        progress.append("first")
        yield
        progress.append("second")
        yield
        progress.append("third")

    handle = runner.add_generator(stepper())
    assert progress == ["first"]
    runner.tick()
    assert progress == ["first", "second"]
    assert not handle.done
    runner.tick()
    assert progress == ["first", "second", "third"]
    assert handle.done


def test_ready_wait_gates_resume():
    """A wait exposing ``ready(now_ms)`` keeps the generator suspended
    while False and resumes it on the tick after ready flips True."""
    runner = Runner(ticks=FakeTicks())
    resumed = []

    class _EventWait:
        def __init__(self):
            self.fired = False

        def ready(self, now_ms):
            return self.fired

    event_wait = _EventWait()

    def waiter():
        resumed.append((yield event_wait))

    handle = runner.add_generator(waiter())
    runner.tick()
    runner.tick()
    assert resumed == []
    event_wait.fired = True
    runner.tick()
    assert len(resumed) == 1
    assert handle.done


def test_ready_wait_deadline_elapses_as_timeout_path():
    """A ready-wait carrying ``next_deadline`` resumes when the deadline
    elapses even though ready stays False, and stays suspended before it."""
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    resumed = []

    class _NeverReadyWait:
        def next_deadline(self, now_ms):
            return 50

        def ready(self, now_ms):
            return False

    def waiter():
        resumed.append((yield _NeverReadyWait()))

    runner.add_generator(waiter())
    runner.tick()
    assert resumed == []
    ticks.advance(60)
    runner.tick()
    assert len(resumed) == 1


# -- Lazy GeneratorHandle re-export (PEP 562) --


def test_generator_handle_attribute_is_lazily_exported():
    """``chumicro_runner.GeneratorHandle`` resolves through the package
    __getattr__ and is the same class ``add_generator`` returns, so the
    generator machinery stays out of the eager import path yet callers
    can still name the handle type."""
    def noop_gen():
        yield _Wait(until_ms=10)

    handle = Runner(ticks=FakeTicks()).add_generator(noop_gen())
    assert chumicro_runner.GeneratorHandle is type(handle)


def test_unknown_package_attribute_raises_attribute_error():
    """An attribute the package neither defines nor lazily re-exports
    raises AttributeError rather than importing something unexpected."""
    with raises(AttributeError):
        _ = chumicro_runner.NotARealSymbol
