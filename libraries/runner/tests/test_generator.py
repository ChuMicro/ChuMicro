"""``Runner.add_generator`` + ``_GeneratorWrapper`` behavior.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Covers the lifecycle a sequential I/O
state machine actually walks — first yield primed at registration, wait
tokens drive check / handle / io_*, ``StopIteration`` auto-removes the
entry, ``cancel()`` fires the generator's ``finally`` block, and
``io_error`` throws into the generator so it can recover (or propagate).
"""

from chumicro_runner import (
    GeneratorHandle,
    ReadReady,
    Runner,
    Sleep,
    WriteReady,
)
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks


class _Sock:
    """Stand-in for a socket-like object — identity is what matters."""


# -- Happy path: registration, run-to-completion, auto-removal --


def test_add_generator_returns_handle_with_done_false():
    runner = Runner(ticks=FakeTicks())

    def noop_gen():
        yield Sleep(until_ms=10)

    handle = runner.add_generator(noop_gen())
    assert isinstance(handle, GeneratorHandle)
    assert handle.done is False


def test_generator_advances_to_first_yield_at_registration():
    # The wrapper primes via .send(None) inside add_generator so the
    # first wait-token is visible to wait()'s _sync_poll_set on the
    # very first tick — without this, the loop sleeps on the wrong
    # deadline because the generator has not run yet.
    sock = _Sock()
    events = []

    def gen():
        events.append("before_yield")
        yield ReadReady(sock)
        events.append("after_yield")

    Runner(ticks=FakeTicks()).add_generator(gen())
    assert events == ["before_yield"]


def test_generator_runs_to_completion_across_ticks():
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    events = []

    def gen():
        events.append("start")
        yield Sleep(until_ms=10)
        events.append("after_sleep")
        yield Sleep(until_ms=20)
        events.append("done")

    handle = runner.add_generator(gen())
    assert events == ["start"]
    assert handle.done is False

    runner.tick()  # now_ms = 0; first Sleep(10) not ready
    assert events == ["start"]
    assert handle.done is False

    ticks.advance(10)
    runner.tick()  # now_ms = 10; first Sleep ready, gen advances
    assert events == ["start", "after_sleep"]
    assert handle.done is False

    ticks.advance(10)
    runner.tick()  # now_ms = 20; second Sleep ready, gen returns
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
        yield Sleep(until_ms=0)  # ready immediately at now_ms=0

    handle = runner.add_generator(short_gen())
    assert len(runner._entries) == 1

    runner.tick()  # Sleep ready at now_ms=0, gen returns, auto-removed.
    assert handle.done is True
    assert len(runner._entries) == 0


# -- Wait-token dispatch on the wrapper --


def test_wrapper_io_socket_tracks_current_wait():
    sock_a = _Sock()
    sock_b = _Sock()
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)

    def gen():
        yield ReadReady(sock_a)
        yield WriteReady(sock_b)

    handle = runner.add_generator(gen())
    wrapper = handle._wrapper
    assert wrapper.io_socket is sock_a
    assert wrapper.io_wants_read is True
    assert wrapper.io_wants_write is False

    runner.tick()  # ReadReady.ready always True; gen advances
    assert wrapper.io_socket is sock_b
    assert wrapper.io_wants_read is False
    assert wrapper.io_wants_write is True

    runner.tick()  # WriteReady.ready always True; gen returns
    assert handle.done is True
    assert wrapper.io_socket is None
    assert wrapper.io_wants_read is False
    assert wrapper.io_wants_write is False


def test_sleep_token_contributes_to_next_deadline():
    # Without this, Runner.wait would sleep on whatever other entry's
    # deadline is nearest — a generator with only a Sleep token would
    # never wake on time.
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)

    def gen():
        yield Sleep(until_ms=500)

    handle = runner.add_generator(gen())
    wrapper = handle._wrapper
    assert wrapper.next_deadline(0) == 500


def test_read_ready_token_does_not_contribute_deadline():
    # ReadReady gates on ipoll wake-ups, not on tick deadlines.
    def gen():
        yield ReadReady(_Sock())

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    assert handle._wrapper.next_deadline(0) is None


# -- EAGAIN retry: re-yield the same token, keep trying --


def test_eagain_retry_loop_advances_when_underlying_call_succeeds():
    # Mirrors the recv_until shape: the helper tries to read, gets a
    # synthetic EAGAIN signal, re-yields the same cached ReadReady,
    # the wrapper sees ready True, calls handle again, and the
    # generator's next iteration succeeds.  This exercises the
    # cache-and-reuse pattern under the wrapper, not just the token.
    sock = _Sock()
    attempts = [0]

    def gen():
        ready = ReadReady(sock)
        while attempts[0] < 3:
            attempts[0] += 1
            yield ready
        # Final successful attempt:
        attempts[0] += 1

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(gen())
    assert attempts == [1]  # primed to first yield

    for _ in range(5):
        if handle.done:
            break
        runner.tick()
    assert handle.done is True
    assert attempts[0] == 4


# -- io_error throws OSError into the generator --


def test_io_error_throws_into_generator_at_current_yield():
    sock = _Sock()
    caught = []

    def gen():
        try:
            yield ReadReady(sock)
        except OSError as error:
            caught.append(error)
        # Returns after handling the error.

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(gen())
    assert handle.done is False

    handle._wrapper.io_error(now_ms=0, eventmask=0)
    assert len(caught) == 1
    assert isinstance(caught[0], OSError)
    # Generator caught the error and returned -> wrapper marked done.
    assert handle.done is True


def test_unhandled_exception_during_advance_marks_done_and_propagates():
    # A generator that raises during a normal resume must not leave a
    # dead entry in the runner; the wrapper drops itself before
    # re-raising so a caller catching the error upstream still sees
    # consistent runner state.
    runner = Runner(ticks=FakeTicks())

    def gen():
        yield Sleep(until_ms=0)
        raise ValueError("synthetic")

    handle = runner.add_generator(gen())
    assert len(runner._entries) == 1

    with raises(ValueError):
        runner.tick()  # Sleep ready at 0; resume hits the raise.
    assert handle.done is True
    assert len(runner._entries) == 0


def test_io_error_unhandled_propagates_done():
    # If the generator does not catch the OSError, it propagates out of
    # gen.throw().  The wrapper marks done and removes itself.  The
    # error currently surfaces to the io_error caller (Runner.wait
    # _dispatch_io_error); a future iteration may log + swallow.
    sock = _Sock()

    def gen():
        yield ReadReady(sock)  # no try/except

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(gen())

    with raises(OSError):
        handle._wrapper.io_error(now_ms=0, eventmask=0)
    assert handle.done is True


# -- Cancellation --


def test_cancel_fires_finally_block_in_generator():
    cleanup_ran = [False]

    def gen():
        try:
            yield Sleep(until_ms=10_000)  # would block forever
        finally:
            cleanup_ran[0] = True

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    assert cleanup_ran[0] is False

    handle.cancel()
    assert cleanup_ran[0] is True
    assert handle.done is True


def test_cancel_is_idempotent():
    def gen():
        yield Sleep(until_ms=10_000)

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    handle.cancel()
    handle.cancel()  # no error; second call is a no-op
    assert handle.done is True


def test_cancel_removes_entry_from_runner():
    runner = Runner(ticks=FakeTicks())

    def gen():
        yield Sleep(until_ms=10_000)

    handle = runner.add_generator(gen())
    assert len(runner._entries) == 1

    handle.cancel()
    assert len(runner._entries) == 0


def test_cancel_after_completion_is_a_noop():
    runner = Runner(ticks=FakeTicks())

    def gen():
        yield Sleep(until_ms=0)

    handle = runner.add_generator(gen())
    runner.tick()  # gen completes
    assert handle.done is True

    # Cancelling an already-done handle should not crash.
    handle.cancel()
    assert handle.done is True


# -- yield from delegation (the canonical use case) --


def test_yield_from_delegation_works_across_helpers():
    # The whole point of the syntax choice: a helper that itself
    # yield-froms another helper composes naturally without an
    # async/await keyword cascade.
    events = []

    def inner_helper(label):
        events.append(f"inner:{label}:start")
        yield Sleep(until_ms=0)
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
        yield Sleep(until_ms=0)
        return "produced-value"

    def consumer():
        result = yield from producer()
        received.append(result)

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(consumer())

    while not handle.done:
        runner.tick()

    assert received == ["produced-value"]
