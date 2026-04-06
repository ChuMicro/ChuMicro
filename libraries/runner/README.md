# chumicro-runner

A tick-based task runner for CircuitPython, MicroPython, and CPython — no async required.

Components implement a `check(now_ms) -> bool` check that gates when a handler fires.  A `Runner` captures time once per tick, checks each service, and batch-fires all due handlers — replacing ad-hoc polling loops with a single standard contract.

## Installation

### CircuitPython (circup)

Register the ChuMicro bundle (remove the other channel first if switching):

```bash
circup bundle-remove ChuMicro/ChuMicro-Bundle-Experimental   # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-runner
```

### MicroPython (mip)

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner
```

### CPython (pip)

```bash
pip install chumicro-runner
```

### Experimental (pre-release) versions

Pre-release builds are published automatically when a library version is bumped.  Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-runner

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_runner

# CPython
pip install chumicro-runner-experimental
```

## Quick example

```python
from chumicro_runner import Runner


class TemperatureSensor:
    """Alert when temperature exceeds a threshold."""

    def __init__(self, threshold=30.0):
        self._threshold = threshold
        self._last_reading = 0.0

    def read_temperature(self):
        """Read from hardware — fast I2C or ADC operation."""
        # On a real board: return self._i2c_device.temperature
        return self._last_reading

    def check(self, now_ms):
        self._last_reading = self.read_temperature()
        return self._last_reading > self._threshold

    def handle(self, now_ms):
        print(f"ALERT: {self._last_reading}°C exceeds {self._threshold}°C")


runner = Runner()
sensor = TemperatureSensor(threshold=30.0)
runner.add(sensor, period_ms=5000)  # check every 5 seconds

while True:
    runner.tick()
```

For simple periodic tasks, no service class is needed:

```python
from chumicro_runner import Runner

runner = Runner()
runner.add_periodic(lambda now_ms: print("blink!"), period_ms=500)

while True:
    runner.tick()
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `Runner(ticks=None)` | Tick-based service loop with shared timestamps |
| `Runner.add(task, handler=None, period_ms=None, start_after_ms=None, run_count=None)` | Register a task; returns a `TaskHandle` |
| `Runner.add_periodic(handler, period_ms, start_after_ms=None, run_count=None)` | Register a periodic handler; returns a `TaskHandle` |
| `Runner.tick()` | Capture time, check services, batch-fire handlers; returns `now_ms` |
| `TaskHandle` | Opaque handle for runtime mutation of a registered service |
| `TaskHandle.set_period(period_ms)` | Add, change, or remove the period (`None` to remove) |
| `TaskHandle.remove()` | Remove this service from the runner |
| `TaskHandle.period_ms` | Read-only: the service period, or `None` |
| `TaskHandle.run_count` | Read-only: remaining run count, or `None` if unlimited |
| `TaskHandle.active` | Read-only: whether the service is still registered |

### Testing

| Symbol | Description |
|---|---|
| `CallRecorder()` | Callable that records handler invocations for test assertions |
| `CallRecorder.calls` | Direct access to the list of recorded `now_ms` values |

## Registration patterns

### Object-based (with `.check()` and `.handle()`)

Pass an object that has `check(now_ms) -> bool` and `handle(now_ms)` methods.  The runner calls `.check()`; if it returns `True`, `.handle()` is queued:

```python
class MotionDetector:
    def __init__(self):
        # On a real board: self._pin = digitalio.DigitalInOut(board.D5)
        pass

    def detect_motion(self):
        """Read PIR sensor pin — fast digital read."""
        # On a real board: return self._pin.value
        return False

    def check(self, now_ms):
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

`add()` and `add_periodic()` return a `TaskHandle` for runtime changes:

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

The `chumicro_runner.testing` module provides `CallRecorder` for verifying that handlers fire at the right times:

```python
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
recorder = CallRecorder()
runner = Runner(ticks=fake)
runner.add_periodic(recorder, period_ms=100)

runner.tick()
assert len(recorder) == 0  # not due yet

fake.advance(100)
runner.tick()
assert recorder.calls == [100]
```

## Platform support

All classes use only basic Python features.  Works identically on CPython, MicroPython, and CircuitPython.

## Memory notes

- `_TaskEntry` and `TaskHandle` use `__slots__` to minimise per-instance memory.
- Handlers are collected into a pre-allocated list and batch-fired, avoiding per-tick allocation.

## Examples

| Example | What it shows |
|---|---|
| `sensor_threshold.py` | Object-based check/handle with a temperature sensor |
| `periodic_blink.py` | Periodic handler with no service class |
| `basic_handler.py` | Handler-only task (fires every tick) |
| `multi_service.py` | Multiple services at different rates |
| `runtime_control.py` | TaskHandle: change period, limit runs, remove at runtime |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `circuitpython_button_led.py` | Button-gated LED on CircuitPython |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `micropython_button_led.py` | Button-gated LED on MicroPython |

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/runner/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/runner/experimental/)**

Browse on GitHub:

- [User guide](docs/guide.md) — the pattern, getting started, writing components
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `CallRecorder` in your tests

## Find this library

**PyPI:** [chumicro-runner](https://pypi.org/project/chumicro-runner/)
**Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) (CircuitPython & MicroPython)
**Source:** [ChuMicro/ChuMicro](https://github.com/ChuMicro/ChuMicro) — cross-runtime Python libraries for ESP32, RP2040, and other microcontrollers.

