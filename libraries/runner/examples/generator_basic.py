"""Generator-driven service: sequential steps written as a top-to-bottom function.

The second sanctioned registration shape (alongside ``add`` and
``add_periodic``).  A generator function suspends via
``yield from sleep_until(ticks_add(ticks_ms(), N))``; the runner
resumes it when the deadline passes.  Sequential code that would
otherwise need an explicit per-state ``check`` / ``handle`` object
reads top-to-bottom.

This example uses only ``sleep_until`` — the simplest helper, no
sockets needed.  Real use lands when ``connect`` / ``send_all`` /
``recv_until`` from ``chumicro_sockets.generators`` orchestrate
non-blocking socket I/O between the sleep checkpoints.

Example output::

    Generator demo starting...
    [    0 ms] tick 1: about to sleep 500 ms
    [  500 ms] tick 2: woke from sleep, doing work
    [  500 ms] tick 3: about to sleep 1000 ms
    [ 1500 ms] tick 4: woke from sleep, finishing
    Generator done -- exiting.

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_ms

tick_counter = 0


def stepwise_work():
    """Demo generator: sleep, work, sleep, work, finish."""
    global tick_counter  # noqa: PLW0603
    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: about to sleep 500 ms")

    yield from sleep_until(ticks_add(ticks_ms(), 500))

    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: woke from sleep, doing work")

    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: about to sleep 1000 ms")

    yield from sleep_until(ticks_add(ticks_ms(), 1000))

    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: woke from sleep, finishing")


runner = Runner()
handle = runner.add_generator(stepwise_work())

print("Generator demo starting...")

while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)

print("Generator done -- exiting.")
