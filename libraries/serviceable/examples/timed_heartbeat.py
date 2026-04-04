"""Heartbeat-integrated handlers — periodic dispatch without a component class.

Demonstrates heartbeat-integrated handlers: the dispatcher creates an
internal ``Heartbeat`` and emits events automatically when the period
elapses.  No component class is needed for simple periodic callbacks.

For comparison, also shows the component-based approach from the
serviceable pattern, where a component wraps a ``Heartbeat`` and emits
events in its ``service()`` method.

Runs on CPython, MicroPython, and CircuitPython without modification.
"""

import time

from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher


def main():
    """Run heartbeat-integrated handlers through the dispatch loop."""
    sink = EventQueueSink(max_size=8)
    dispatcher = SimpleEventDispatcher()

    # Register a periodic handler — no component class needed.
    handle = dispatcher.register(
        "led.blink",
        lambda e: print("  blink!"),
        period_ms=500,
    )

    print(f"Registered: {handle}")
    print(f"  period_ms = {handle.period_ms}")
    print(f"  priority  = {handle.priority}")
    print()

    runner = ServiceRunner([], sink, dispatcher)

    print("Running heartbeat handler (Ctrl+C to stop)...")

    try:
        while True:
            runner.service_once()
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
