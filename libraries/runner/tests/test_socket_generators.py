"""Runner driving generators: ``sleep_until`` plus socket integration.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Covers the runner-owned ``sleep_until``
helper directly and end-to-end under ``Runner.add_generator``, then
drives a full connect / send / recv lifecycle through the runner using
the socket helpers that now live in ``chumicro_sockets.generators`` —
proving the scheduler wrapper and the socket helpers compose.
"""

import errno

from chumicro_runner import IO_WRITE, Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_timing.waits import Signal, wait_for

# -- sleep_until -----------------------------------------------------


def test_sleep_until_yields_deadline_wait():
    # The helper does no time math: it publishes the deadline and returns after
    # one suspension.  Gating it is the driver's job, with the driver's clock.
    gen = sleep_until(1000)
    first = gen.send(None)
    assert first.next_deadline(0) == 1000
    assert getattr(first, "io_socket", None) is None
    assert getattr(first, "ready", None) is None
    try:
        gen.send(0)
    except StopIteration:
        pass
    else:
        raise AssertionError("sleep_until did not return after its single yield")


def test_sleep_until_resumes_after_deadline_under_runner():
    ticks = FakeTicks()
    resumed = []

    def sleeper():
        yield from sleep_until(ticks.ticks_add(ticks.ticks_ms(), 500))
        resumed.append(True)

    runner = Runner(ticks=ticks)
    handle = runner.add_generator(sleeper())

    # Before the deadline the wrapper's check() gate stays closed.
    runner.tick()
    assert not handle.done
    assert resumed == []

    # Advancing past the deadline opens the gate and the generator finishes.
    ticks.advance(500)
    runner.tick()
    assert handle.done
    assert resumed == [True]


# -- Full-stack socket integration through Runner.add_generator ------


def test_connect_handles_yield_from_in_outer_generator():
    # The canonical use site — ``sock = yield from connect(connector)``.
    sock = FakeSocket()
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)

    received_sock = []

    def outer():
        result = yield from connect(connector)
        received_sock.append(result)

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(outer())
    while not handle.done:
        runner.tick()

    assert received_sock == [sock]


def test_connect_threads_runner_now_ms_into_connector_tick():
    # The wrapper sends the runner's now_ms in at each resume; connect
    # must pass that into connector.tick rather than a hardcoded 0, so a
    # connector that tracks its own deadline sees the real clock.
    sock = FakeSocket()

    class _RecordingConnector:
        io_socket = None

        def __init__(self):
            self.state = "awaiting_dns"
            self.socket = None
            self.last_error = None
            self.ticks_seen = []
            self._steps = ["awaiting_tcp", "ready"]

        def io_interest(self, now_ms):
            return IO_WRITE

        def next_deadline(self, now_ms):
            return None

        def tick(self, now_ms):
            self.ticks_seen.append(now_ms)
            if self.state in ("ready", "failed"):
                return
            self.state = self._steps.pop(0)
            if self.state == "ready":
                self.socket = sock

        def cancel(self):
            self.state = "failed"

    connector = _RecordingConnector()
    received = []

    def outer():
        result = yield from connect(connector)
        received.append(result)

    fake = FakeTicks()
    runner = Runner(ticks=fake)
    handle = runner.add_generator(outer())
    now_ms = 0
    while not handle.done:
        fake.advance(1000)
        now_ms = runner.tick()

    assert received == [sock]
    # The priming tick (during add_generator) has no clock yet, so 0;
    # the resume tick threads the runner's real now_ms through.
    assert connector.ticks_seen[0] == 0
    assert now_ms > 0
    assert connector.ticks_seen[-1] == now_ms


def test_full_lifecycle_connect_send_recv_under_runner():
    # Drives a complete generator service under the runner — connect
    # advances the connector, send_all writes a probe, recv_until reads
    # the echo.  Verifies the helpers compose end-to-end through
    # Runner.add_generator without manual gen.send plumbing.
    sock = FakeSocket()
    sock.enqueue_recv(b"echo:hello\n")
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)
    received = []

    def echo_run():
        connected_sock = yield from connect(connector)
        try:
            yield from send_all(connected_sock, b"hello\n")
            reply = yield from recv_until(connected_sock, b"\n", max_bytes=100)
            received.append(reply)
        finally:
            connected_sock.close()

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(echo_run())
    while not handle.done:
        runner.tick()

    assert bytes(sock.sent) == b"hello\n"
    assert received == [b"echo:hello\n"]
    assert sock.closed is True


# -- Signal / wait_for -----------------------------------------------


def test_signal_wait_for_returns_value_set_by_callback():
    # wait_for suspends until another service's handler sets the
    # signal, then resumes on the following tick and returns the
    # stored value.
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    outcome = []
    link_up = Signal()

    def waiter():
        outcome.append((yield from wait_for(link_up)))

    handle = runner.add_generator(waiter())
    runner.tick()
    runner.tick()
    assert outcome == []

    runner.add(handler=lambda now_ms: link_up.set("192.0.2.7"), run_count=1)
    runner.tick()
    runner.tick()
    assert outcome == ["192.0.2.7"]
    assert handle.done


def test_signal_wait_for_deadline_raises_etimedout_inside_generator():
    # Past deadline_ms with the signal unset, wait_for raises
    # OSError(ETIMEDOUT) inside the generator body — catchable there —
    # and clears the timeout it parked on the signal.
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    caught = []
    never = Signal()

    def waiter():
        try:
            yield from wait_for(never, deadline_ms=100)
        except OSError as error:
            caught.append(error.args[0])

    handle = runner.add_generator(waiter())
    runner.tick()
    assert caught == []
    ticks.advance(150)
    runner.tick()
    assert caught == [errno.ETIMEDOUT]
    assert handle.done
    assert never.next_deadline(0) is None


def test_signal_wait_contributes_no_wake_timeout():
    # A pending signal wait exposes no deadline of its own, so
    # _compute_timeout stays governed by the other services — the
    # setter's wake source is what un-parks the loop.
    ticks = FakeTicks()
    runner = Runner(ticks=ticks)
    signal = Signal()

    def waiter():
        yield from wait_for(signal)

    runner.add_generator(waiter())
    assert runner._compute_timeout(ticks.ticks_ms()) is None


# -- Driving the same helpers with no runner at all ------------------


def _should_resume(wait, now_ms, ticks):
    """The whole resumption gate, in the caller's own clock.

    Three cases, checked in order: a wait that answers ``ready`` decides for
    itself; a wait that publishes ``next_deadline`` resumes once that tick lands;
    anything else may be resumed on any pass.  Every compare goes through *ticks*,
    so a clock with its own wrap behaviour measures its own deadlines.
    """
    ready = getattr(wait, "ready", None)
    if ready is not None and ready(now_ms):
        return True
    next_deadline = getattr(wait, "next_deadline", None)
    deadline_ms = None if next_deadline is None else next_deadline(now_ms)
    if deadline_ms is not None:
        return ticks.ticks_diff(now_ms, deadline_ms) >= 0
    return ready is None


def _drive_without_runner(generator, ticks):
    """Run *generator* to completion on a bare loop an adopter could write.

    This is what lifting the socket helpers into a codebase with no
    ``chumicro_runner`` costs: the gate above, and nothing about ``io_socket`` or
    ``io_interest``, which only exist so a scheduler can sleep instead of spin.
    """
    wait = generator.send(None)
    while True:
        now_ms = ticks.ticks_ms()
        if _should_resume(wait, now_ms, ticks):
            try:
                wait = generator.send(now_ms)
            except StopIteration:
                return
        ticks.advance(1)


def test_socket_helpers_run_to_completion_without_a_runner():
    ticks = FakeTicks()
    sock = FakeSocket()
    sock.enqueue_recv(b"echo\n")
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)
    replies = []

    def echo():
        connected = yield from connect(connector)
        yield from send_all(connected, b"probe\n")
        replies.append((yield from recv_until(connected, b"\n", max_bytes=64)))

    _drive_without_runner(echo(), ticks)

    assert replies == [b"echo\n"]
    assert sock.sent == b"probe\n"


def test_runner_gates_deadlines_with_the_clock_it_was_given():
    # Regression: the generator wrapper's own check() gate must use the clock
    # passed to Runner(ticks=...).  A 4-day deadline on a non-wrapping clock
    # aliases to "elapsed" under chumicro_timing's 2**29 compare, which would
    # resume the task on its very first tick.
    class UnwrappedTicks:
        def __init__(self):
            self.now = 600_000_000

        def ticks_ms(self):
            return self.now

        def ticks_add(self, ticks_value, delta):
            return ticks_value + delta

        def ticks_diff(self, end, start):
            return end - start

        def sleep_ms(self, duration_ms):
            pass

    ticks = UnwrappedTicks()
    resumed = []

    def sleeper():
        yield from sleep_until(ticks.ticks_add(ticks.ticks_ms(), 4 * 86_400_000))
        resumed.append(True)

    runner = Runner(ticks=ticks)
    handle = runner.add_generator(sleeper())
    runner.tick()

    assert resumed == []
    assert not handle.done


def test_sleep_until_sleeps_its_full_span_without_a_runner():
    # The bare-loop gate honours next_deadline with the caller's own ticks_diff,
    # so a clock-free sleep_until still sleeps its whole span off the runner.
    ticks = FakeTicks()
    finished_at = []

    def sleeper():
        yield from sleep_until(ticks.ticks_add(ticks.ticks_ms(), 500))
        finished_at.append(ticks.ticks_ms())

    _drive_without_runner(sleeper(), ticks)

    assert finished_at == [500]
