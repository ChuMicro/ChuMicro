"""Runtime service control — advanced ecosystem patterns.

Demonstrates how the serviceable and timing libraries work together:

- Adjusting service periods at runtime via ``ServiceHandle``
- Removing services dynamically
- Using ``Heartbeat`` alongside ``ServiceRunner`` for custom timing
  logic that lives outside the runner
- Using the runner's ``now_ms`` return value for external decisions

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import ServiceRunner
from chumicro_timing import Heartbeat


def log_data(now_ms):
    """Simulate a data logging operation."""
    print(f"  [{now_ms} ms] logged sensor data")


def check_wifi(now_ms):
    """Simulate a Wi-Fi connectivity check."""
    print(f"  [{now_ms} ms] Wi-Fi: connected")


def main():
    """Show runtime service control with ServiceHandle and Heartbeat."""
    runner = ServiceRunner()

    # Register services and keep their handles for runtime control.
    log_handle = runner.add_periodic(log_data, period_ms=1000)
    wifi_handle = runner.add_periodic(check_wifi, period_ms=2000)

    # A Heartbeat used independently — not managed by the runner.
    # Useful for timing decisions that don't fit the service pattern,
    # like switching modes after a certain duration.
    mode_timer = Heartbeat(period_ms=3000)

    print("Phase 1: normal operation (logging=1s, wifi=2s)...\n")

    switched = False
    end_time = time.monotonic() + 6
    while time.monotonic() < end_time:
        # service_once() returns the shared timestamp.
        now = runner.service_once()

        # Use now_ms with an independent Heartbeat for a timed mode switch.
        if not switched and mode_timer.poll(now):
            print("\n  >> Phase 2: fast logging (250 ms), Wi-Fi removed\n")
            log_handle.set_period(250)
            wifi_handle.remove()
            switched = True

        time.sleep(0.1)  # simulate other work between ticks

    # ServiceHandle exposes read-only state for inspection.
    print(f"\nDone. Log active: {log_handle.active}, "
          f"period: {log_handle.period_ms} ms")
    print(f"Wi-Fi active: {wifi_handle.active}")


if __name__ == "__main__":
    main()

