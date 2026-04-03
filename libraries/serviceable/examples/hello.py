"""Serviceable heartbeat — standard dispatch loop.

Demonstrates the serviceable pattern with two heartbeats emitting
distinct event types into a shared sink.  A ServiceRunner dispatches
each event to the correct handler.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat


def main():
    """Run two heartbeats through the serviceable dispatch loop."""
    fast_beat = Heartbeat(period_ms=500, event_type="fast.tick")
    slow_beat = Heartbeat(period_ms=2000, event_type="slow.tick")

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("fast.tick", lambda e: print("fast!"))
    dispatcher.register("slow.tick", lambda e: print("  slow!"))

    runner = ServiceRunner([fast_beat, slow_beat], sink, dispatcher)

    print("Running serviceable heartbeat (Ctrl+C to stop)...")

    try:
        while True:
            runner.service_once()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
