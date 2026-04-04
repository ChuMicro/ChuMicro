"""Basic handler patterns — the most common way to use ServiceRunner.

Shows two fundamental patterns:

1. **Every-tick handler** — runs on every call to ``service_once()``.
   Use for work that should happen as often as possible (polling
   buttons, updating displays, processing input).

2. **Periodic handler** — runs on a time schedule.
   Use for work on a fixed interval (blinking LEDs, logging data,
   sending heartbeats).

No service objects or check functions needed — just a callable.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner

tick_count = 0


def count_ticks(now_ms):
    """Increment the tick counter.

    Runs every tick — use this pattern for work that should
    happen as often as possible (e.g., scanning button inputs).
    """
    global tick_count  # noqa: PLW0603
    tick_count += 1


def report_status(now_ms):
    """Print a periodic status report.

    Runs on a fixed schedule — use this pattern for work that
    should happen at regular intervals.
    """
    print(f"  [{now_ms} ms] status: {tick_count} ticks processed")


def main():
    """Run an every-tick counter alongside a periodic status report."""
    runner = ServiceRunner()

    # Every-tick handler: fires on every service_once() call.
    runner.add(handler=count_ticks)

    # Periodic handler: fires once per second.
    runner.add_periodic(report_status, period_ms=1000)

    print("Running for 3 seconds...\n")

    end_time = time.monotonic() + 3
    while time.monotonic() < end_time:
        runner.service_once()
        time.sleep(0.1)  # simulate other work between ticks

    print(f"\nDone. Total ticks: {tick_count}")


if __name__ == "__main__":
    main()

