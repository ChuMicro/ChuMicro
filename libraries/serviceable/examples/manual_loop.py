"""Shared-timestamp loop — the manual way.

Shows the core pattern that ServiceRunner automates: capture ticks_ms()
once per iteration and share it across all components.  Start here to
understand what the runner does, then see with_runner.py for the
shorter version.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_timing import Heartbeat, ticks_ms


def main():
    """Run two heartbeats with a shared timestamp until interrupted."""
    led_beat = Heartbeat(period_ms=500)
    report_beat = Heartbeat(period_ms=3000)

    print("Running manual loop (Ctrl+C to stop)...")

    try:
        while True:
            # Capture time ONCE per loop — all components see the same moment.
            now = ticks_ms()

            if led_beat.poll(now):
                print("  blink!")
            if report_beat.poll(now):
                print("  sending report...")

            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

