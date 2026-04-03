"""Multiple heartbeats at different rates.

Demonstrates running several independent timers in a single main loop.
Each timer fires at its own rate without blocking the others.
"""

import time

from chumicro_timing import Heartbeat


def main():
    """Run three heartbeats at 200 ms, 1 s, and 5 s until interrupted."""
    fast = Heartbeat(period_ms=200)
    medium = Heartbeat(period_ms=1000)
    slow = Heartbeat(period_ms=5000)

    print("Running multiple heartbeats (Ctrl+C to stop)...")

    try:
        while True:
            if fast.poll():
                print("  fast (200 ms)")
            if medium.poll():
                print("  medium (1 s)")
            if slow.poll():
                print("  slow (5 s)")

            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
