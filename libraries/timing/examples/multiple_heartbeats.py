"""Multiple heartbeats at different rates.

Demonstrates the shared-timestamp pattern: capture ``ticks_ms()`` once
per loop iteration and pass the same value to every heartbeat.  This
ensures all components see the same moment in time — no drift between
calls.

On a real board, each heartbeat could drive a different LED or sensor
polling rate.

Example output::

    Running multiple heartbeats (Ctrl+C to stop)...

      fast (200 ms)
      fast (200 ms)
      fast (200 ms)
      fast (200 ms)
      fast (200 ms)
      medium (1 s)
      fast (200 ms)
      ...
      slow (5 s)
      ...

Runs on CPython, MicroPython, and CircuitPython.
"""

import time

from chumicro_timing import Heartbeat, ticks_ms


def main():
    """Run three heartbeats at 200 ms, 1 s, and 5 s until interrupted."""
    fast = Heartbeat(period_ms=200)
    medium = Heartbeat(period_ms=1000)
    slow = Heartbeat(period_ms=5000)

    print("Running multiple heartbeats (Ctrl+C to stop)...\n")

    try:
        while True:
            now = ticks_ms()
            if fast.poll(now):
                print("  fast (200 ms)")
            if medium.poll(now):
                print("  medium (1 s)")
            if slow.poll(now):
                print("  slow (5 s)")

            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
