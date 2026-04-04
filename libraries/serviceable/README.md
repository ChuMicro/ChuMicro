# chumicro-serviceable

A tick-based service pattern for Chumicro libraries.

Components implement a `service(now_ms) -> bool` check that gates when a handler fires.  A `ServiceRunner` captures time once per tick, checks each service, and batch-fires all due handlers — replacing ad-hoc polling loops with a single standard contract.

## Installation

```bash
# CPython (pip)
pip install chumicro-serviceable

# CircuitPython (circup) — coming soon
# circup install chumicro-serviceable

# MicroPython (mip) — coming soon
# import mip; mip.install("chumicro-serviceable")
```

## Quick example

```python
from chumicro_serviceable import ServiceRunner


class TemperatureSensor:
    """Alert when temperature exceeds a threshold."""

    def __init__(self, threshold=30.0):
        self._threshold = threshold
        self._last_reading = 0.0

    def read_temperature(self):
        """Read from hardware — fast I2C or ADC operation."""
        # On a real board: return self._i2c_device.temperature
        return self._last_reading

    def service(self, now_ms):
        self._last_reading = self.read_temperature()
        return self._last_reading > self._threshold

    def handle(self, now_ms):
        print(f"ALERT: {self._last_reading}°C exceeds {self._threshold}°C")


runner = ServiceRunner()
sensor = TemperatureSensor(threshold=30.0)
runner.add(sensor, period_ms=5000)  # check every 5 seconds

while True:
    runner.service_once()
```

For simple periodic tasks, no service class is needed:

```python
from chumicro_serviceable import ServiceRunner

runner = ServiceRunner()
runner.add_periodic(lambda now_ms: print("blink!"), period_ms=500)

while True:
    runner.service_once()
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `ServiceRunner(ticks=None)` | Tick-based service loop with shared timestamps |
| `ServiceRunner.add(service, handler=None, period_ms=None)` | Register a service; returns a `ServiceHandle` |
| `ServiceRunner.add_periodic(handler, period_ms)` | Register a periodic handler; returns a `ServiceHandle` |
| `ServiceRunner.service_once()` | Capture time, check services, batch-fire handlers; returns `now_ms` |
| `ServiceHandle` | Opaque handle for runtime mutation of a registered service |
| `ServiceHandle.set_period(period_ms)` | Add, change, or remove the period (`None` to remove) |
| `ServiceHandle.remove()` | Remove this service from the runner |
| `ServiceHandle.period_ms` | Read-only: the service period, or `None` |
| `ServiceHandle.active` | Read-only: whether the service is still registered |

### Testing

| Symbol | Description |
|---|---|
| `CallRecorder()` | Callable that records handler invocations for test assertions |
| `CallRecorder.calls` | Direct access to the list of recorded `now_ms` values |

## Registration patterns

### Object-based (service with `.service()` and `.handle()`)

Pass an object that has `service(now_ms) -> bool` and `handle(now_ms)` methods.  The runner calls `.service()`; if it returns `True`, `.handle()` is queued:

```python
class MotionDetector:
    def __init__(self):
        # On a real board: self._pin = digitalio.DigitalInOut(board.D5)
        pass

    def detect_motion(self):
        """Read PIR sensor pin — fast digital read."""
        # On a real board: return self._pin.value
        return False

    def service(self, now_ms):
        return self.detect_motion()

    def handle(self, now_ms):
        print("Motion!")

runner.add(MotionDetector())
```

### Callable-based (check function + handler)

Pass a callable check function and a handler.  Both can be lambdas, bound methods, or regular functions:

```python
runner.add(
    lambda now_ms: sensor.ready(),
    handler=lambda now_ms: process(sensor.read()),
)
```

### Handler-only (no check, fires every tick)

Pass just a handler with no service check:

```python
runner.add(handler=lambda now_ms: poll_buttons(now_ms))
```

### Periodic (fires every N milliseconds)

No service check needed — the handler fires on schedule:

```python
handle = runner.add_periodic(toggle_led, period_ms=500)
handle.set_period(1000)  # change rate at runtime
```

## Runtime mutation

`add()` and `add_periodic()` return a `ServiceHandle` for runtime changes:

```python
handle = runner.add(sensor, period_ms=5000)

# Speed up.
handle.set_period(1000)

# Remove the period — service runs every tick.
handle.set_period(None)

# Remove entirely.
handle.remove()
```

## Testing your components

The `chumicro_serviceable.testing` module provides `CallRecorder` for verifying that handlers fire at the right times:

```python
from chumicro_serviceable.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
recorder = CallRecorder()
runner = ServiceRunner(ticks=fake)
runner.add_periodic(recorder, period_ms=100)

runner.service_once()
assert len(recorder) == 0  # not due yet

fake.advance(100)
runner.service_once()
assert recorder.calls == [100]
```

## Platform support

All classes use only basic Python features.  Works identically on CPython, MicroPython, and CircuitPython.

## Memory notes

- `_ServiceEntry` and `ServiceHandle` use `__slots__` to minimise per-instance memory.
- Handlers are collected into a pre-allocated list and batch-fired, avoiding per-tick allocation.

## Docs

- [User guide](docs/guide.md) — the pattern, getting started, writing components
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `CallRecorder` in your tests
