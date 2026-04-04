"""Direct sink usage — manual service and drain without ServiceRunner.

Shows how to use EventQueueSink directly when you want full control
over the service-drain-dispatch cycle rather than using ServiceRunner.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

from chumicro_serviceable import EventQueueSink
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks


class PeriodicPinger:
    """A component that emits ping events at a regular interval."""

    EVENT_PING = "pinger.ping"

    def __init__(self, period_ms, ticks=None):
        """Create a pinger that emits every *period_ms* milliseconds."""
        self._heartbeat = Heartbeat(period_ms=period_ms, ticks=ticks)

    def service(self, event_sink, now_ms):
        """Check the heartbeat and emit a ping event if due."""
        if self._heartbeat.poll(now_ms):
            event_sink.emit(self, self.EVENT_PING)


def main():
    """Service a component manually and inspect events from the sink."""
    fake = FakeTicks()
    pinger = PeriodicPinger(period_ms=100, ticks=fake)
    sink = EventQueueSink(max_size=8)

    print("Direct sink usage — manual service loop\n")

    for tick in range(1, 6):
        fake.advance(100)
        now = fake.ticks_ms()
        pinger.service(sink, now)

        while sink.has_events():
            event = sink.pop()
            print(f"  tick {tick}: got {event.event_type} from {event.source}")

    print(f"\nDrained all events. Sink length: {len(sink)}")


if __name__ == "__main__":
    main()

