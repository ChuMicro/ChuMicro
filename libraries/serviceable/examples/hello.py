"""Serviceable heartbeat — standard dispatch loop.

Demonstrates the serviceable pattern: a Heartbeat component emits events
into a shared sink, and a ServiceRunner dispatches them to handlers.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat


def main():
    """Run a heartbeat through the serviceable dispatch loop."""
    heartbeat = Heartbeat(period_ms=1000)

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register(Heartbeat.EVENT_TICK, lambda e: print("beat!"))

    runner = ServiceRunner([heartbeat], sink, dispatcher)

    print("Running serviceable heartbeat (Ctrl+C to stop)...")

    try:
        while True:
            runner.service_once()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
