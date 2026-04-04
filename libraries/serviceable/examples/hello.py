"""Simple serviceable dispatch loop with handle-based registration.

Demonstrates a component that participates in the serviceable dispatch
loop, and shows how ``ServiceRunner.add()`` returns a ``ServiceHandle``
for inspecting and mutating the registration at runtime.

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

    def service(self, event_sink, now_ms):
        """Increment the counter; emit an event on every Nth call."""
        self._count += 1
        if self._count % self._every_n == 0:
            event_sink.emit(self, self.EVENT_MILESTONE, self._count)


def main():
    """Run a custom counter component through the serviceable dispatch loop."""
    counter = Counter(every_n=5)

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()

    # Register a handler for the counter's milestone event.
    handle = dispatcher.register(
        Counter.EVENT_MILESTONE,
        lambda e: print(f"  milestone reached: {e.data} ticks"),
    )
    print(f"Registered handler: {handle}")

    # add() returns a ServiceHandle for runtime mutation.
    runner = ServiceRunner(sink, dispatcher)
    svc_handle = runner.add(counter)
    print(f"Service handle: {svc_handle}")

    print("Running counter component (20 ticks)...")

    for _ in range(20):
        runner.service_once()
        time.sleep(0.05)

    # Unregister the handler via its handle.
    handle.unregister()
    print(f"Handler after unregister: {handle}")

    # Remove the service via its handle.
    svc_handle.remove()
    print(f"Service after remove: {svc_handle}")
    print("Done.")


if __name__ == "__main__":
    main()
