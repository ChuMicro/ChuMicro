# chumicro-serviceable

A standard service-and-event pattern for Chumicro libraries.

Components implement `service(event_sink)` to do one tick of work and emit events.  A `ServiceRunner` calls all components and dispatches events to handlers — replacing ad-hoc polling and drain loops with a single standard contract.

## Installation

```bash
pip install chumicro-serviceable
```

## Quick example

```python
from chumicro_serviceable import EventQueueSink, ServiceRunner, SimpleEventDispatcher
from chumicro_timing import Heartbeat

heartbeat = Heartbeat(period_ms=1000)

sink = EventQueueSink(max_size=16)
dispatcher = SimpleEventDispatcher()
dispatcher.register(Heartbeat.EVENT_TICK, lambda e: print("beat!"))

runner = ServiceRunner([heartbeat], sink, dispatcher)

while True:
    runner.service_once()
```

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Docs

- [User guide](docs/guide.md)
- [API reference](docs/api.md)
