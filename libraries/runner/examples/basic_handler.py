"""Basic handler patterns — the most common way to use Runner.

- **Every-tick handler** — fires on every ``tick()`` call.
  Use for work that must run as often as possible (polling buttons,
  reading input buffers).
- **Periodic handler** — fires on a fixed time schedule.
  Use for regular intervals (blinking LEDs, logging, heartbeats).

No task objects needed — just pass a callable and optionally a period.

Example output::

    Running...

      [1005 ms] status report (10 ticks)
      [2003 ms] status report (20 ticks)
      [2003 ms] heartbeat
      [3008 ms] status report (30 ticks)
      [4002 ms] status report (40 ticks)
      [4002 ms] heartbeat
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_runner import Runner

tick_count = 0


def poll_inputs(now_ms: int) -> None:
    """Poll hardware inputs — runs every tick.

    On a real board this might scan a button matrix or read
    a UART buffer.  Here it just counts ticks.

    Args:
        now_ms: Current tick value.
    """
    global tick_count  # noqa: PLW0603
    tick_count += 1


def report_status(now_ms: int) -> None:
    """Print a periodic status report.

    Args:
        now_ms: Current tick value.
    """
    print(f"  [{now_ms} ms] status report ({tick_count} ticks)")


def heartbeat(now_ms: int) -> None:
    """Print a heartbeat.

    Args:
        now_ms: Current tick value.
    """
    print(f"  [{now_ms} ms] heartbeat")


runner = Runner()

# Every-tick: fires on every tick() call.
runner.add(handler=poll_inputs)

# Periodic: fires once per second.
runner.add_periodic(report_status, period_ms=1000)

# Periodic: fires every two seconds.
runner.add_periodic(heartbeat, period_ms=2000)

print("Running...\n")

while True:
    # tick() captures time once, checks all tasks, and fires
    # any that are due.  Every-tick handlers run on every call;
    # periodic handlers run only when their interval has elapsed.
    runner.tick()

    # In a real project, the rest of your main loop goes here.
    # The sleep just keeps this demo from flooding the console.
    time.sleep(0.1)
