"""Wait-token allocation profile — cached reuse must stay flat.

CPython-only lane: uses :mod:`tracemalloc` + :mod:`gc` to confirm that
a generator helper which constructs one wait-token **outside** its loop
and reuses it across yields produces no per-iteration heap growth.

The cache-reuse pattern is what keeps steady-state allocation at zero:
without it, a helper looping on ``yield ReadReady(sock)`` allocates a
fresh token per iteration and the per-tick allocation budget evaporates.
This test pins the contract so a future edit that inadvertently
allocates inside ``ready`` / ``result`` (e.g. returning a tuple,
building an error message) surfaces here.
"""

#: CPython-only lane (uses stdlib tracemalloc + gc).  Not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import tracemalloc

from chumicro_runner import ReadReady, Sleep, WriteReady


def _measure_growth(operation, *, warmup_iterations=50, sample_iterations=500):
    """Run *operation* warmup times then sample times, measuring retained
    growth across the sample window after GC.  Returns the byte delta.

    Matches the convention used by ``test_memory_pressure_pytest.py``.
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


class TestCachedReadReadyDoesNotGrow:
    """A helper looping on a hoisted ``ReadReady`` token should not
    accumulate heap across repeated ``ready`` / ``result`` calls."""

    def test_cached_read_ready_reuse_stays_flat(self):
        sock = object()
        token = ReadReady(sock)

        def operation():
            # Mirrors the inner-loop shape of ``recv_until``: probe
            # readiness, then unpack the resume value.  Both calls in
            # production hit the same token reference each iteration.
            assert token.ready(0) is True
            assert token.result(0) is sock

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"cached ReadReady reuse leaked {growth} bytes over 500 iterations"
        )


class TestCachedWriteReadyDoesNotGrow:
    """Same contract for the write side — ``send_all`` reuses one
    ``WriteReady`` token across EAGAIN yields."""

    def test_cached_write_ready_reuse_stays_flat(self):
        sock = object()
        token = WriteReady(sock)

        def operation():
            assert token.ready(0) is True
            assert token.result(0) is sock

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"cached WriteReady reuse leaked {growth} bytes over 500 iterations"
        )


class TestCachedSleepDoesNotGrow:
    """A cached ``Sleep`` token whose deadline is repeatedly compared
    against advancing ``now_ms`` values must not grow — ``ready`` does
    arithmetic only, ``result`` returns the input."""

    def test_cached_sleep_reuse_stays_flat(self):
        token = Sleep(until_ms=1_000_000)
        counter = [0]

        def operation():
            counter[0] += 1
            now_ms = counter[0]
            # ``ready`` returns False while now_ms < until_ms (the
            # interesting hot-path shape: many cheap comparisons
            # before the deadline trips).
            token.ready(now_ms)
            token.result(now_ms)

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"cached Sleep reuse leaked {growth} bytes over 500 iterations"
        )
