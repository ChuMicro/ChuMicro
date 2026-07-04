"""Runtime task control: advanced ecosystem patterns.

Demonstrates how the runner and timing libraries work together:

- Adjusting task periods at runtime via ``TaskHandle``
- Removing tasks dynamically
- Using ``Rate`` alongside ``Runner`` for custom timing
  logic that lives outside the runner
- Using the runner's ``now_ms`` return value for external decisions

After 10 seconds, the example switches to "fast mode": logging
speeds up and the Wi-Fi check is removed.

Example output::

    Running...

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

from chumicro_runner import Runner
from chumicro_timing import Rate, ticks_ms


def log_data(now_ms: int) -> None:
    """Log sensor data.

    Args:
        now_ms: Current tick value.
    """
    print(f"  [{now_ms} ms] logged sensor data")


def check_wifi(now_ms: int) -> None:
    """Check Wi-Fi connectivity.

    Args:
        now_ms: Current tick value.
    """
    print(f"  [{now_ms} ms] Wi-Fi: connected")


runner = Runner()

# Register tasks and keep their handles for runtime control.
log_handle = runner.add_periodic(log_data, period_ms=1000)
wifi_handle = runner.add_periodic(check_wifi, period_ms=2000)

# Rate used standalone, not registered with the runner.
# Use it for timing decisions outside the runner's task model,
# like switching operating modes after a duration.
mode_timer = Rate(10000, ticks_ms())

switched = False

print("Running...\n")

while True:
    # tick() returns the shared timestamp.
    now = runner.tick()

    # Use now_ms with an independent Rate for a timed mode switch.
    if not switched and mode_timer.due(now):
        print("\n  >> Switching to fast mode: "
              "logging every 250 ms, Wi-Fi removed\n")
        log_handle.set_period(250)
        wifi_handle.remove()
        switched = True

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.1)
