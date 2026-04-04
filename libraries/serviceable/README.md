# chumicro-serviceable

Tick-based service loop with shared timestamps for Chumicro applications.

`ServiceRunner` captures `ticks_ms()` once per tick and distributes the shared timestamp to all registered components — ensuring every part of your main loop sees the same moment in time.

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
from chumicro_timing import Heartbeat

led_beat = Heartbeat(period_ms=500)
runner = ServiceRunner()

while True:
    now = runner.tick()
    if led_beat.poll(now):
        print("blink!")
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `ServiceRunner(services=None, ticks=None)` | Tick-based loop runner that captures shared timestamps |
| `ServiceRunner.tick()` | Capture time, service all components, return `now_ms` |
| `ServiceRunner.add(service)` | Register a component to be serviced each tick |

### Testing

| Symbol | Description |
|---|---|
| `FakeService()` | Stub component that records `service(now_ms)` calls |
| `FakeService.ticks` | List of `now_ms` values passed to `service()` |

## Writing active components

Any object with a `service(now_ms)` method can be registered with the runner. No base class or import is required:

```python
class ButtonScanner:
    def __init__(self, pin):
        self._pin = pin
        self.pressed = False

    def service(self, now_ms):
        self.pressed = self._pin.value
```

## Testing your components

Use `FakeService` to verify that a runner or loop calls components correctly:

```python
from chumicro_serviceable.testing import FakeService

svc = FakeService()
svc.service(42)
assert svc.ticks == [42]
```

## Platform support

Works identically on CPython, MicroPython, and CircuitPython. Depends on `chumicro-timing` for the default tick source.

## Docs

- [User guide](docs/guide.md) — shared timestamps, runner usage, active components
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `FakeService` in your tests
