"""Allocation profile for the fetch generator's EAGAIN recv loop.

CPython-only lane: uses :mod:`tracemalloc` + :mod:`gc` to confirm the
receive loop reuses its cached scratch buffer and read-wait, retaining
nothing per EAGAIN iteration.  A regression that allocates inside the
loop (a new wait per yield, a per-iteration buffer copy, a debug
f-string) surfaces here.  The transient ``OSError(EAGAIN)`` the fake
raises each poll is collected, so it does not count toward retained
growth.

Threshold matches the other memory-pressure lanes: under 2 KiB of
growth across 500 sample iterations.
"""

#: CPython-only lane (uses stdlib tracemalloc + gc).  Not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import gc
import tracemalloc

from chumicro_requests.generators import fetch
from chumicro_requests.testing import make_factory
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


def test_fetch_eagain_recv_loop_no_growth():
    sock = FakeSocket()
    sock.enqueue_eagain_for_recv(count=100_000)  # keep the recv loop EAGAIN-ing
    ticks = FakeTicks()
    # Large timeout (within the tick wrap-period delta limit) and a clock
    # that never advances here, so the deadline check never fires.
    gen = fetch(make_factory(sock), "GET", "http://example.test/", ticks=ticks, timeout_ms=1_000_000)
    gen.send(None)  # advance through connect's first yield (the connector)
    gen.send(0)     # connect ready, request sent, first recv -> EAGAIN -> read-wait

    gc.collect()
    tracemalloc.start()
    try:
        for _ in range(50):
            gen.send(0)
        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        for _ in range(500):
            gen.send(0)
        gc.collect()
        final, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    growth = final - baseline
    assert growth < 2048, (
        f"fetch EAGAIN recv loop leaked {growth} bytes over 500 iterations"
    )
