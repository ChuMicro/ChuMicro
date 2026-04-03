"""Timeout check using tick functions directly.

Shows how to use ticks_ms / ticks_diff / ticks_add for custom timing
logic that doesn't fit the Heartbeat pattern — for example, detecting
whether an operation took too long.
"""

import time

from chumicro_timing import ticks_add, ticks_diff, ticks_ms

TIMEOUT_MS = 500


def simulate_work():
    """Pretend to do something that takes a variable amount of time."""
    import random

    delay = random.uniform(0.1, 0.8)
    print(f"  Working for {delay:.2f}s...")
    time.sleep(delay)


def main():
    """Run five timeout checks and report whether each finished in time."""
    print(f"Running timeout checks with {TIMEOUT_MS} ms limit (Ctrl+C to stop)...\n")

    try:
        for attempt in range(1, 6):
            start = ticks_ms()
            deadline = ticks_add(start, TIMEOUT_MS)

            simulate_work()

            now = ticks_ms()
            remaining = ticks_diff(deadline, now)

            if remaining <= 0:
                elapsed = ticks_diff(now, start)
                print(f"  Attempt {attempt}: TIMEOUT after {elapsed} ms\n")
            else:
                elapsed = ticks_diff(now, start)
                print(f"  Attempt {attempt}: OK in {elapsed} ms ({remaining} ms to spare)\n")
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
