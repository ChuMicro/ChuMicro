# User Guide

## Overview

`chumicro-runner` provides a standard pattern for active components in the ChuMicro ecosystem.  Instead of each library inventing its own `poll()` / callback API, every active component implements two methods:

```python
def check(self, now_ms: int) -> bool:
    """Check whether the handler should fire.

    Args:
        now_ms: Current tick timestamp in milliseconds.

    Returns:
        True if the handler should fire this tick.
    """

def handle(self, now_ms: int) -> None:
    """React to the condition detected by check().

    Args:
        now_ms: Current tick timestamp in milliseconds.
    """
```

A shared `Runner` captures time once per tick, checks each service, and batch-fires all due handlers.  This replaces ad-hoc polling loops with a single standard contract.

## The pattern

1. **Services** implement `check(now_ms) -> bool` — they check a condition and return whether the handler should fire.
2. **Handlers** implement `handle(now_ms)` — they react when the service says "go".
3. **Runner** ties it together: capture time → check all services → batch-fire all due handlers.

Services can be objects with `.check()` and `.handle()` methods, or plain callables (lambdas, functions, bound methods).

## Getting started

```python
from chumicro_runner import Runner

class TemperatureSensor:
    """Alert when temperature exceeds a threshold.

    Args:
        threshold: Temperature in °C that triggers an alert.
    """

    def __init__(self, threshold: float = 30.0) -> None:
        self._threshold = threshold
        self._last_reading = 0.0

    def read_temperature(self) -> float:
        """Read from hardware — fast I2C or ADC operation."""
        # On a real board: return self._i2c_device.temperature
        return self._last_reading

    def check(self, now_ms: int) -> bool:
        """Return True when the reading exceeds the threshold.

        Args:
            now_ms: Current tick timestamp (unused here).

        Returns:
            True if the last reading exceeds the threshold.
        """
        self._last_reading = self.read_temperature()
        return self._last_reading > self._threshold

    def handle(self, now_ms: int) -> None:
        """Print an alert with the current reading.

        Args:
            now_ms: Current tick timestamp.
        """
        print(f"ALERT: {self._last_reading}°C exceeds {self._threshold}°C")

sensor = TemperatureSensor(threshold=30.0)
runner = Runner()
runner.add(sensor, period_ms=5000)

while True:
    runner.tick()
```

## Shared timestamps

`Runner.tick()` captures `ticks_ms()` once and passes the resulting timestamp to every service.  This ensures all services in the loop see the same moment in time, preventing drift between independent clock reads on slow microcontrollers.

The method returns `now_ms` so user code can use it alongside the service loop:

```python
while True:
    now = runner.tick()
    if some_heartbeat.poll(now):
        do_something()
```

## Registration patterns

### Object-based

Pass an object with `.check(now_ms) -> bool` and `.handle(now_ms)`:

```python
class MotionDetector:
    """Gate-based motion detector using a PIR sensor."""

    def __init__(self) -> None:
        # On a real board: self._pin = digitalio.DigitalInOut(board.D5)
        pass

    def detect_motion(self) -> bool:
        """Read PIR sensor pin — fast digital read."""
        # On a real board: return self._pin.value
        return False

    def check(self, now_ms: int) -> bool:
        """Return True when motion is detected.

        Args:
            now_ms: Current tick timestamp.

        Returns:
            True if the PIR sensor reads high.
        """
        return self.detect_motion()

    def handle(self, now_ms: int) -> None:
        """React to detected motion.

        Args:
            now_ms: Current tick timestamp.
        """
        print("Motion!")

runner.add(MotionDetector())
```

You can override `.handle()` by passing a `handler` argument:

```python
runner.add(detector, handler=lambda now_ms: send_alert())
```

### Callable-based

Pass a check function and a handler — both can be lambdas, functions, or bound methods:

```python
runner.add(
    lambda now_ms: light_sensor.level() < 20,
    handler=lambda now_ms: turn_on_lights(),
)
```

### Handler-only

Pass just a handler with no check — it fires every tick (or per period):

```python
runner.add(handler=lambda now_ms: scan_buttons(now_ms))
```

### Periodic

No check needed — the handler fires on a schedule:

```python
runner.add_periodic(
    lambda now_ms: print("blink!"),
    period_ms=500,
)
```

## Period-gated services

Pass `period_ms` to `add()` and the runner will only check the service when the period elapses.  Services without a period are checked every tick.

```python
runner = Runner()

# Sensor is only checked every 5 seconds.
handle = runner.add(sensor, period_ms=5000)

# Button scanner runs every tick.
runner.add(button_scanner)
```

You can change or remove the period at runtime via the `TaskHandle`:

```python
# Speed up.
handle.set_period(1000)

# Remove the period — service runs every tick again.
handle.set_period(None)

# Remove the service entirely.
handle.remove()
```

### Delayed start

Pass `start_after_ms` to delay the first check.  Subsequent checks use `period_ms`:

```python
# Wait 2 seconds, then check every 5 seconds.
runner.add(sensor, period_ms=5000, start_after_ms=2000)
```

### Limited runs

Pass `run_count` to auto-remove a task after a set number of handler fires:

```python
# Fire exactly 3 times, then stop.
runner.add_periodic(calibrate, period_ms=1000, run_count=3)
```

## Multiple services

The pattern scales to many services with no extra boilerplate:

```python
runner = Runner()
runner.add(motion_detector)
runner.add(temperature_sensor, period_ms=5000)
runner.add(
    lambda now_ms: light_level < 20,
    handler=lambda now_ms: turn_on_lights(),
)
runner.add_periodic(toggle_led, period_ms=500)
runner.add_periodic(log_status, period_ms=10000)

while True:
    runner.tick()
```

## Batch firing

All services are checked first, then all due handlers fire in sequence.  This guarantees that handlers see a consistent view of the world — no handler modifies state while other services are still being checked.

```
tick():
  1. Capture ticks_ms() → now_ms
  2. For each entry:
     - Period gate: skip if not due
     - Check gate: skip if check(now_ms) returns False
     - Queue handler
  3. Fire all queued handlers with now_ms
```

## Memory notes

- Handlers are collected into a pre-allocated list and batch-fired, avoiding per-tick allocation.
- No `collections.deque` or ring buffers are required.

## Testing tasks

The `chumicro_runner.testing` module provides `CallRecorder` — a callable that records handler invocations for assertions in host-side tests:

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

See the [testing helpers](testing.md) page for detailed usage.

## Platform notes

All classes use only basic Python features and work identically on CPython, MicroPython, and CircuitPython.  No `abc`, `typing`, or `asyncio` dependencies.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples) directory contains complete runnable scripts:

| Example | What it shows |
|---|---|
| `basic_handler.py` | Simplest handler-only registration |
| `periodic_blink.py` | Periodic handler with `add_periodic()` |
| `sensor_threshold.py` | Object-based check/handle with simulated sensor |
| `multi_service.py` | Multiple services in one runner |
| `runtime_control.py` | `TaskHandle` for dynamic period changes and removal |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `circuitpython_button_led.py` | Button + LED gate pattern on CircuitPython |
| `micropython_button_led.py` | Button + LED gate pattern on MicroPython |

Simulated examples run on CPython.  Hardware examples (`circuitpython_*` / `micropython_*`) require a real board — see the setup notes in each file.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · [PyPI](https://pypi.org/project/chumicro-runner/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
