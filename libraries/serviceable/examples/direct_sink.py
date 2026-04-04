"""Direct sink usage — manual service and drain without ServiceRunner.

Shows how to use EventQueueSink directly when you want full control
over the service-drain-dispatch cycle rather than using ServiceRunner.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

from chumicro_serviceable import EventQueueSink
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks


def main():
    """Service a heartbeat manually and inspect events from the sink."""
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake, event_type="heartbeat.tick")
    sink = EventQueueSink(max_size=8)

    print("Direct sink usage — manual service loop\n")

    for tick in range(1, 6):
        fake.advance(100)
        heartbeat.service(sink)

        while sink.has_events():
            event = sink.pop()
            print(f"  tick {tick}: got {event.event_type} from {event.source}")

    print(f"\nDrained all events. Sink length: {len(sink)}")


if __name__ == "__main__":
    main()

