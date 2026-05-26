"""Generator-driven service: sequential I/O written as a top-to-bottom function.

The second sanctioned registration shape (alongside ``add`` and
``add_periodic``).  A generator function suspends via ``yield`` of a
wait-token; the runner resumes it when the token reports ready.
Sequential code that would otherwise need an explicit per-state
``check`` / ``handle`` object reads top-to-bottom.

This example yields only ``Sleep`` tokens — the simplest token, no
sockets needed.  The substrate it exercises is the same one socket
generator helpers (``connect`` / ``send_all`` / ``recv_until``) will
compose against once they land in ``chumicro_sockets``.

Example output::

    Generator demo starting...
    [    0 ms] tick 1: about to sleep 500 ms
    [  500 ms] tick 2: woke from sleep, doing work
    [  500 ms] tick 3: about to sleep 1000 ms
    [ 1500 ms] tick 4: woke from sleep, finishing
    Generator done — exiting.

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner, Sleep
from chumicro_timing import ticks_add, ticks_ms

tick_counter = 0


def stepwise_work():
    """Demo generator: sleep, work, sleep, work, finish.

    A real generator-driven service would yield ``ReadReady`` /
    ``WriteReady`` for socket I/O between the sleep checkpoints.
    """
    global tick_counter  # noqa: PLW0603
    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: about to sleep 500 ms")

    yield Sleep(until_ms=ticks_add(ticks_ms(), 500))

    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: woke from sleep, doing work")

    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: about to sleep 1000 ms")

    yield Sleep(until_ms=ticks_add(ticks_ms(), 1000))

    tick_counter += 1
    print(f"[{ticks_ms():5d} ms] tick {tick_counter}: woke from sleep, finishing")


runner = Runner()
handle = runner.add_generator(stepwise_work())

print("Generator demo starting...")

while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)

print("Generator done -- exiting.")
