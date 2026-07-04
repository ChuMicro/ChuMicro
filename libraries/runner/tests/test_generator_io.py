"""``_GeneratorWrapper`` I/O surface: poll interest, EAGAIN retry, io_error.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Split from ``test_generator.py`` (the
lifecycle suite) so each file's whole-file compile transient stays under
the CircuitPython unix-lane heap budget; ``_Sock`` / ``_Wait`` are shared
via ``_generator_helpers``.

Asserts the wrapper's duck-typed ``io_socket`` / ``io_interest(now_ms)``
reads off the yielded wait, and that ``io_error`` throws ``OSError`` into
the generator (recover or propagate) on the same isolated dispatch lane
``tick()`` uses.
"""

from _generator_helpers import _Sock, _Wait
from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

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
    assert wrapper.io_interest(0) == IO_READ

    runner.tick()  # socket-based wait fires every tick; gen advances
    assert wrapper.io_socket is sock_b
    assert wrapper.io_interest(0) == IO_WRITE

    runner.tick()  # second wait fires; gen returns
    assert handle.done is True
    assert wrapper.io_socket is None
    assert wrapper.io_interest(0) == 0


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
        # no io_interest, no next_deadline

    def gen():
        yield _MinimalWait()

    handle = Runner(ticks=FakeTicks()).add_generator(gen())
    wrapper = handle._wrapper
    assert wrapper.io_socket is _MinimalWait.io_socket
    assert wrapper.io_interest(0) == 0
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
    # The wrapper re-raises an OSError the generator body doesn't catch
    # (so the runner can observe and count it) and marks itself done.
    # This pins the wrapper's re-raise contract by calling it directly;
    # the runner isolates that re-raise so it can't escape wait().
    sock = _Sock()

    def gen():
        yield _Wait(sock=sock, want_read=True)  # no try/except

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(gen())

    with raises(OSError):
        handle._wrapper.io_error(now_ms=0, eventmask=0)
    assert handle.done is True


def test_unhandled_io_error_through_dispatch_is_isolated():
    # A generator that lets the io_error OSError propagate is dropped and
    # counted at Runner._dispatch_io_error, so a POLLERR / POLLHUP during
    # wait() can't kill the reactor loop — symmetry with tick()'s
    # handler-fault isolation.
    sock = _Sock()
    faults = []
    runner = Runner(
        ticks=FakeTicks(),
        on_handler_error=lambda handle, error: faults.append(error),
    )

    def gen():
        yield _Wait(sock=sock, want_read=True)  # no try/except

    handle = runner.add_generator(gen())
    assert len(runner._entries) == 1

    # Dispatch through the runner path, not the wrapper directly; must not raise.
    runner._dispatch_io_error(sock, eventmask=0, now_ms=0)

    assert handle.done is True
    assert len(runner._entries) == 0
    assert runner.handler_errors == 1
    assert len(faults) == 1
    assert isinstance(faults[0], OSError)


def test_io_error_callback_that_raises_is_isolated():
    # An on_handler_error hook that itself raises while reporting an
    # io_error fault gets swallowed and counted too, so a buggy hook
    # can't re-break the wait() loop the isolation just protected.
    sock = _Sock()

    def on_error(handle, error):
        raise RuntimeError("buggy hook")

    runner = Runner(ticks=FakeTicks(), on_handler_error=on_error)

    def gen():
        yield _Wait(sock=sock, want_read=True)  # no try/except

    runner.add_generator(gen())
    runner._dispatch_io_error(sock, eventmask=0, now_ms=0)  # must not raise

    assert runner.handler_errors == 2
