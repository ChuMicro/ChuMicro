"""Heartbeat with the serviceable pattern — decoupled dispatch.

Demonstrates using Heartbeat.service() with chumicro-serviceable
to decouple timing events from the code that handles them.

Two heartbeats emit distinct event types into a shared sink.
A ServiceRunner drains the sink and routes each event to the
correct handler — the heartbeats never call the handlers directly.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat


def main():
    """Run two heartbeats through a serviceable dispatch loop."""
    led_beat = Heartbeat(period_ms=500, event_type="led.blink")
    report_beat = Heartbeat(period_ms=3000, event_type="report.send")

    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()
    dispatcher.register("led.blink", lambda e: print("  blink!"))
    dispatcher.register("report.send", lambda e: print("  sending report..."))

    runner = ServiceRunner([led_beat, report_beat], sink, dispatcher)

    print("Running serviceable heartbeat (Ctrl+C to stop)...")

    try:
        while True:
            runner.service_once()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()

