"""Runtime service control — advanced ecosystem patterns.

Demonstrates how the serviceable and timing libraries work together:

- Adjusting service periods at runtime via ``ServiceHandle``
- Removing services dynamically
- Using ``Heartbeat`` alongside ``ServiceRunner`` for custom timing
  logic that lives outside the runner
- Using the runner's ``now_ms`` return value for external decisions

After 10 seconds, the example switches to "fast mode" — logging
speeds up and the Wi-Fi check is removed.

Example output::

    Running... (Ctrl+C to stop)

    [1005 ms] logged sensor data
    [2003 ms] Wi-Fi: connected
    [2003 ms] logged sensor data
    [3008 ms] logged sensor data
    ...

    >> Switching to fast mode: logging every 250 ms, Wi-Fi removed

    [10102 ms] logged sensor data
    [10354 ms] logged sensor data
    [10605 ms] logged sensor data
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_serviceable import ServiceRunner
from chumicro_timing import Heartbeat


def log_data(now_ms):
    """Log sensor data."""
    print(f"  [{now_ms} ms] logged sensor data")


def check_wifi(now_ms):
    """Check Wi-Fi connectivity."""
    print(f"  [{now_ms} ms] Wi-Fi: connected")


def main():
    """Show runtime service control with ServiceHandle and Heartbeat."""
    runner = ServiceRunner()

    # Register services and keep their handles for runtime control.
    log_handle = runner.add_periodic(log_data, period_ms=1000)
    wifi_handle = runner.add_periodic(check_wifi, period_ms=2000)

    # A Heartbeat used independently — not managed by the runner.
    # Useful for timing decisions that don't fit the service pattern,
    # like switching operating modes after a duration.
    mode_timer = Heartbeat(period_ms=10000)

    switched = False

    print("Running... (Ctrl+C to stop)\n")

    while True:
        # service_once() returns the shared timestamp.
        now = runner.service_once()

        # Use now_ms with an independent Heartbeat for a timed mode switch.
        if not switched and mode_timer.poll(now):
            print("\n  >> Switching to fast mode: "
                  "logging every 250 ms, Wi-Fi removed\n")
            log_handle.set_period(250)
            wifi_handle.remove()
            switched = True

        time.sleep(0.1)


if __name__ == "__main__":
    main()

