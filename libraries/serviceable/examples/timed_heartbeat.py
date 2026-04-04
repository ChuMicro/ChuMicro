"""Timed component — using the shared timestamp for periodic work.

Demonstrates a component that uses the shared ``now_ms`` timestamp
from ``service()`` to drive a ``Heartbeat`` for periodic event emission.
The timestamp is captured once by ``ServiceRunner`` and shared with
all components, preventing drift.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat


class PeriodicReporter:
    """A component that emits a report event at a regular interval."""

    EVENT_REPORT = "reporter.report"

    def __init__(self, period_ms):
        """Create a reporter that emits every *period_ms* milliseconds."""
        self._heartbeat = Heartbeat(period_ms=period_ms)

    def service(self, event_sink, now_ms):
        """Check the heartbeat and emit a report event if due."""
        if self._heartbeat.poll(now_ms):
            event_sink.emit(self, self.EVENT_REPORT)


def main():
    """Run two timed reporters through the serviceable dispatch loop."""
    fast = PeriodicReporter(period_ms=500)
    slow = PeriodicReporter(period_ms=2000)

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register(PeriodicReporter.EVENT_REPORT, lambda e: print("  report!"))

    runner = ServiceRunner([fast, slow], sink, dispatcher)

    print("Running timed reporters (Ctrl+C to stop)...")

    try:
        while True:
            runner.service_once()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

