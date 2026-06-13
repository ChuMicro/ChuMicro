"""``Runner.add_generator`` + ``_GeneratorWrapper`` behavior.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Covers the lifecycle a sequential I/O
state machine actually walks — first yield primed at registration,
yielded waits drive check / handle / io_*, ``StopIteration``
auto-removes the entry, ``cancel()`` fires the generator's
``finally`` block, ``io_error`` throws into the generator so it can
recover (or propagate).

The wait shape is **duck-typed**: this file constructs ad-hoc ``_Wait``
stubs with the four protocol attributes (``io_socket``,
``io_wants_read``, ``io_wants_write``, ``next_deadline``) and asserts
the wrapper inspects them via ``getattr``.  No imports of the private
wait classes from ``chumicro_runner.generators`` — proving the
protocol is genuinely duck-typed rather than tied to specific types.
"""

from chumicro_runner import GeneratorHandle, Runner
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks


class _Sock:
    """Stand-in for a socket-like object — identity is what matters."""


class _Wait:
    """Ad-hoc wait stub matching the wrapper's duck-typed protocol.

    Any object exposing these four attributes works as a wait — the
    wrapper reads them via ``getattr`` with defaults, so missing
    attributes degrade gracefully.  This stub sets all four so tests
    can express any wait shape (socket-driven, deadline-driven, or
    both) with one constructor.
    """

    def __init__(self, *, sock=None, want_read=False, want_write=False, until_ms=None):
        self.io_socket = sock
        self.io_wants_read = want_read
        self.io_wants_write = want_write
        self.next_deadline = until_ms


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


# -- Wait dispatch on the wrapper (duck-typed via getattr) ----------


def test_wrapper_io_socket_tracks_current_wait():
    sock_a = _Sock()
    sock_b = _Sock()
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)

    def gen():
        yield _Wait(sock=sock_a, want_read=True)
        yield _Wait(sock=sock_b, want_write=True)

    handle = runner.add_generator(gen())
    wrapper = handle._wrapper
    assert wrapper.io_socket is sock_a
    assert wrapper.io_wants_read is True
    assert wrapper.io_wants_write is False

    runner.tick()  # socket-based wait fires every tick; gen advances
    assert wrapper.io_socket is sock_b
    assert wrapper.io_wants_read is False
    assert wrapper.io_wants_write is True

    runner.tick()  # second wait fires; gen returns
    assert handle.done is True
    assert wrapper.io_socket is None
    assert wrapper.io_wants_read is False
    assert wrapper.io_wants_write is False


def test_sleep_contributes_to_next_deadline():
    # Without this, Runner.wait would sleep on whatever other entry's
    # deadline is nearest — a generator with only a deadline wait
    # would never wake on time.
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)

    def gen():
        yield _Wait(until_ms=500)

    handle = runner.add_generator(gen())
    wrapper = handle._wrapper
    assert wrapper.next_deadline(0) == 500


def test_socket_wait_does_not_contribute_deadline():
    # Socket waits leave next_deadline at None; ipoll wake-ups gate
    # the loop instead of a deadline.
    def gen():
        yield _Wait(sock=_Sock(), want_read=True)

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    assert handle._wrapper.next_deadline(0) is None


def test_socket_wait_with_deadline_resumes_before_deadline():
    # A wait carrying both a socket and a deadline (a socket read with a
    # timeout) resumes every tick on socket-readiness rather than staying
    # gated until the deadline — otherwise ready bytes would sit unread.
    # The deadline is far ahead, yet both ticks resume the generator.
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    resumes = []

    def gen():
        yield _Wait(sock=_Sock(), want_read=True, until_ms=10_000)
        resumes.append(1)
        yield _Wait(sock=_Sock(), want_read=True, until_ms=10_000)
        resumes.append(2)

    handle = runner.add_generator(gen())
    runner.tick()  # now=0, far before the 10_000 deadline
    runner.tick()
    assert resumes == [1, 2]
    assert handle.done is True


def test_wrapper_tolerates_bare_object_missing_protocol_attrs():
    # The wrapper uses getattr with defaults, so a yielded value that
    # exposes only some of the protocol still works — the missing
    # attributes degrade to None / False.  This is what lets a
    # ``SocketConnector`` (which exposes all four attributes) and a
    # tiny private wait (which only exposes io_socket + a wants flag)
    # both flow through the same code path.
    class _MinimalWait:
        io_socket = _Sock()
        # no io_wants_*, no next_deadline

    def gen():
        yield _MinimalWait()

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    wrapper = handle._wrapper
    assert wrapper.io_socket is _MinimalWait.io_socket
    assert wrapper.io_wants_read is False
    assert wrapper.io_wants_write is False
    assert wrapper.next_deadline(0) is None


# -- EAGAIN-style retry: re-yield the same wait, keep trying --------


def test_eagain_retry_loop_advances_when_underlying_call_succeeds():
    # Mirrors the recv_until shape: the helper tries to read, gets a
    # synthetic EAGAIN signal, re-yields the same cached wait, the
    # wrapper sees check True (socket-based waits always do), calls
    # handle again, generator's next iteration succeeds.  Exercises
    # the cache-and-reuse pattern under the wrapper.
    sock = _Sock()
    attempts = [0]

    def gen():
        cached_wait = _Wait(sock=sock, want_read=True)
        while attempts[0] < 3:
            attempts[0] += 1
            yield cached_wait
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


# -- io_error throws OSError into the generator ---------------------


def test_io_error_throws_into_generator_at_current_yield():
    sock = _Sock()
    caught = []

    def gen():
        try:
            yield _Wait(sock=sock, want_read=True)
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


def test_unhandled_exception_during_advance_marks_done_and_is_isolated():
    # A generator that raises during a normal resume is dropped from the
    # runner (the wrapper marks done and removes its entry), and tick()
    # isolates and counts the fault rather than propagating it, so the
    # reactor loop survives.
    runner = Runner(ticks=FakeTicks())

    def gen():
        yield _Wait(until_ms=0)
        raise ValueError("synthetic")

    handle = runner.add_generator(gen())
    assert len(runner._entries) == 1

    runner.tick()  # sleep ready at 0; resume hits the raise, isolated.

    assert handle.done is True
    assert len(runner._entries) == 0
    assert runner.handler_errors == 1


def test_io_error_unhandled_propagates_done():
    # If the generator does not catch the OSError, it propagates out of
    # gen.throw().  The wrapper marks done and removes itself.  The
    # error currently surfaces to the io_error caller (Runner.wait
    # _dispatch_io_error); a future iteration may log + swallow.
    sock = _Sock()

    def gen():
        yield _Wait(sock=sock, want_read=True)  # no try/except

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(gen())

    with raises(OSError):
        handle._wrapper.io_error(now_ms=0, eventmask=0)
    assert handle.done is True


# -- Cancellation ----------------------------------------------------


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
