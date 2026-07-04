"""runner reactor: heap-drift profile for ``Runner.tick`` + ``Runner.wait``.

These tests run on CPython using :mod:`tracemalloc` to confirm that
steady-state ``tick + wait`` cycles do not accumulate heap.  They
catch Python-level leaks in the runner-reactor sync path: the
``_registered_interest`` dict, the ``wanted_now`` scratch list inside
``_sync_poll_set``, the ``ticks_diff``-driven ``_compute_timeout``,
and the ``FakePoller`` bookkeeping that a test like this drives.

These don't replicate device-level fragmentation (CP / MP allocators
are different), but they prove the pure-Python data structures the
runner maintains converge: any growing list / dict / accumulating
closure surfaces here as monotonically rising allocation counts.

The thresholds match the standard set by the per-library memory-
pressure tests (mqtt / requests / websockets): under 2 KiB of growth
across 500 sample iterations after warmup + GC.
"""

#: CPython-only lane (uses stdlib tracemalloc + gc).  Not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import select
import tracemalloc

from chumicro_runner import IO_READ, IO_WRITE, Runner
from chumicro_runner.testing import FakePoller
from chumicro_timing.testing import FakeTicks


class _StableService:
    """Service with frozen ``io_interest``.  Mimics a connected client
    that keeps wanting read for a long stretch."""

    def __init__(self, sock):
        self.io_socket = sock
        self.wants_read = True
        self.wants_write = False

    def io_interest(self, now_ms):
        interest = 0
        if self.wants_read:
            interest |= IO_READ
        if self.wants_write:
            interest |= IO_WRITE
        return interest

    def check(self, now_ms):
        return False

    def handle(self, now_ms):
        pass


class _FlappingService:
    """Service whose ``io_interest`` flips read<->write every ``handle()``.

    Exercises the register / modify / unregister diff path so a leak in
    the registered-set dict or the ``_sync_poll_set`` housekeeping
    surfaces in steady state.
    """

    def __init__(self, sock):
        self.io_socket = sock
        self.wants_read = True
        self.wants_write = False
        self._toggle = False

    def io_interest(self, now_ms):
        interest = 0
        if self.wants_read:
            interest |= IO_READ
        if self.wants_write:
            interest |= IO_WRITE
        return interest

    def check(self, now_ms):
        return True

    def handle(self, now_ms):
        self._toggle = not self._toggle
        self.wants_read = not self._toggle
        self.wants_write = self._toggle


def _reset_poller_bookkeeping(poller):
    """Clear the FakePoller's accumulating record lists.

    The fake records every register / modify / unregister / ipoll call
    for assertion in unit tests, but those lists grow per iteration
    and would mask the underlying runner-side allocation we're
    measuring.  Reset between operations so growth attributable to the
    runner is what surfaces.
    """
    poller.register_calls.clear()
    poller.modify_calls.clear()
    poller.unregister_calls.clear()
    poller.ipoll_calls.clear()


def _measure_growth(operation, *, warmup_iterations=50, sample_iterations=500):
    """Run *operation* warmup_iterations times, then sample_iterations
    more, measuring how much heap memory accumulated AFTER GC.

    Returns ``growth_bytes``.  A clean implementation produces growth
    near zero; significant positive growth indicates a leak.
    """
    gc.collect()
    tracemalloc.start()
    try:
        for _ in range(warmup_iterations):
            operation()
        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()

        for _ in range(sample_iterations):
            operation()
        gc.collect()
        final, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return final - baseline


class TestRunnerWaitNoLeakStable:
    """tick + wait cycles with a service whose ``io_*`` never changes
    should produce no per-cycle retained allocation: the poll set is
    populated once during warmup and stays untouched thereafter."""

    def test_stable_service_no_growth(self):
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        service = _StableService(sock=object())
        runner.add(service, period_ms=10)

        def operation():
            _reset_poller_bookkeeping(poller)
            now_ms = runner.tick()
            runner.wait(now_ms)
            ticks.advance(1)

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"stable tick + wait leaked {growth} bytes over 500 iterations"
        )


class TestRunnerWaitNoLeakFlapping:
    """A service flipping its ``io_interest`` between read and write every
    tick exercises the register / modify path.  The sync should call
    ``poller.modify`` repeatedly but accumulate nothing."""

    def test_flapping_service_no_growth(self):
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        service = _FlappingService(sock=object())
        runner.add(service, period_ms=1)

        def operation():
            _reset_poller_bookkeeping(poller)
            now_ms = runner.tick()
            runner.wait(now_ms)
            ticks.advance(1)

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"flapping tick + wait leaked {growth} bytes over 500 iterations"
        )


class TestRunnerWaitNoLeakCycledRegistration:
    """Add and remove the same service across cycles.  Each registration
    creates a TaskHandle; each removal drops it.  Steady-state should
    not retain TaskHandle objects from prior cycles."""

    def test_add_remove_cycle_no_growth(self):
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        sock = object()

        def operation():
            _reset_poller_bookkeeping(poller)
            service = _StableService(sock=sock)
            handle = runner.add(service, period_ms=10)
            now_ms = runner.tick()
            runner.wait(now_ms)
            handle.remove()
            # Run one more tick + wait so the unregister path fires.
            now_ms = runner.tick()
            runner.wait(now_ms)
            ticks.advance(1)

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"add/remove cycle leaked {growth} bytes over 500 iterations"
        )


class TestPollSetRegistrationStaysBounded:
    """A long stretch of stable-service operation must not grow
    ``_registered_interest`` beyond the live socket count."""

    def test_registered_interest_stays_at_one_entry(self):
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        service = _StableService(sock=object())
        runner.add(service, period_ms=10)

        for _ in range(50):
            now_ms = runner.tick()
            runner.wait(now_ms)
            ticks.advance(1)

        assert len(runner._registered_interest) == 1


class TestFakePollerObservedMaskMatchesService:
    """Sanity check: when ``io_interest`` returns ``IO_READ`` only, the
    FakePoller is asked to register the socket with the POLLIN flag and
    nothing else."""

    def test_read_only_service_registers_pollin_only(self):
        ticks = FakeTicks()
        poller = FakePoller()
        runner = Runner(ticks=ticks, poller=poller)
        sock = object()
        service = _StableService(sock=sock)
        runner.add(service, period_ms=10)

        runner.tick()
        runner.wait(ticks.ticks_ms())

        assert (sock, select.POLLIN) in poller.register_calls
