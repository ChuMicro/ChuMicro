"""Retained-allocation guard for the socket-generator helpers.

CPython-only lane: uses :mod:`tracemalloc` + :mod:`gc` to confirm the
EAGAIN-loop inside ``send_all`` / ``recv_until`` / ``recv_exact`` retains
no memory across iterations — the cached wait is reused, not re-allocated
and stashed, and the accumulator does not grow without bound.  Measures
net-retained bytes after ``gc.collect()``, so it catches a leak; it does
not catch transient per-iteration churn (a slice freed by refcount the
same tick is invisible here).  The on-device zero-allocation contract is
verified separately with ``gc.mem_alloc()`` under ``gc.disable()``.

The threshold matches the existing memory-pressure tests:  under
2 KiB of growth across 500 sample iterations.
"""

#: CPython-only lane (uses stdlib tracemalloc + gc).  Not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import tracemalloc

from chumicro_sockets.generators import recv_exact, recv_until, send_all
from chumicro_sockets.testing import FakeSocket


def _measure_growth(operation, *, warmup_iterations=50, sample_iterations=500):
    """Run *operation* warmup + sample times; return retained bytes growth.

    Matches the convention used by the other memory-pressure tests.
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


class TestSendAllEagainLoopStaysFlat:
    """A ``send_all`` EAGAIN spin retains nothing across iterations:
    the cached write-wait is reused, not re-allocated and stashed."""

    def test_send_all_eagain_iteration_no_growth(self):
        sock = FakeSocket()

        def operation():
            sock.enqueue_eagain_for_send(count=1)
            gen = send_all(sock, b"x")
            gen.send(None)  # one EAGAIN yield
            try:
                gen.send(0)  # send succeeds, gen returns
            except StopIteration:
                pass
            sock.sent.clear()  # don't let the byte log dominate growth

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"send_all EAGAIN loop leaked {growth} bytes over 500 iterations"
        )


class TestRecvUntilEagainLoopStaysFlat:
    """A cached read-wait should let a recv_until polling loop run
    indefinitely with bounded heap."""

    def test_recv_until_eagain_iteration_no_growth(self):
        sock = FakeSocket()

        def operation():
            sock.enqueue_eagain_for_recv(count=1)
            sock.enqueue_recv(b"\n")
            gen = recv_until(sock, b"\n", max_bytes=100)
            gen.send(None)
            try:
                gen.send(0)
            except StopIteration:
                pass

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"recv_until EAGAIN loop leaked {growth} bytes over 500 iterations"
        )


class TestRecvExactEagainLoopStaysFlat:
    """Same EAGAIN-loop contract for ``recv_exact``."""

    def test_recv_exact_eagain_iteration_no_growth(self):
        sock = FakeSocket()

        def operation():
            sock.enqueue_eagain_for_recv(count=1)
            sock.enqueue_recv(b"abc")
            gen = recv_exact(sock, 3, max_bytes=4096)
            gen.send(None)
            try:
                gen.send(0)
            except StopIteration:
                pass

        growth = _measure_growth(operation)
        assert growth < 2048, (
            f"recv_exact EAGAIN loop leaked {growth} bytes over 500 iterations"
        )
