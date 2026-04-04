"""Custom serviceable component — writing your own service(event_sink).

Demonstrates how to create a component that participates in the
serviceable dispatch loop.  No base class or import from
chumicro-serviceable is needed — just implement service(event_sink).

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher


class Counter:
    """A component that emits an event every N calls to service()."""

    EVENT_MILESTONE = "counter.milestone"

    def __init__(self, every_n=5):
        """Create a counter that emits every *every_n* service calls."""
        self._every_n = every_n
        self._count = 0

    def service(self, event_sink):
        """Increment the counter; emit an event on every Nth call."""
        self._count += 1
        if self._count % self._every_n == 0:
            event_sink.emit(self, self.EVENT_MILESTONE, self._count)


def main():
    """Run a custom counter component through the serviceable dispatch loop."""
    counter = Counter(every_n=5)

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register(
        Counter.EVENT_MILESTONE,
        lambda e: print(f"  milestone reached: {e.data} ticks"),
    )

    runner = ServiceRunner([counter], sink, dispatcher)

    print("Running custom counter component (20 ticks)...")

    for _ in range(20):
        runner.service_once()
        time.sleep(0.05)

    print("Done.")


if __name__ == "__main__":
    main()

