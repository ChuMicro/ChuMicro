# chumicro-runner

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**A tick-based task scheduler — no async, no threads, just `runner.tick()` in your loop.**

Register services with check/handle methods, add periodic callbacks, and the runner dispatches everything on a shared timestamp. Each service runs on its own schedule while you write the interesting parts. Works on CircuitPython, MicroPython, and CPython. Built on [timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses bundles to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-runner
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner
```

### CPython (pip)

```bash
pip install chumicro-runner
```

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped.  Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-runner

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_runner

# CPython
pip install chumicro-runner-experimental
```

</details>

## Quick example

```python
from chumicro_runner import Runner

runner = Runner()
runner.add_periodic(lambda now_ms: print("blink!"), period_ms=500)

while True:
    runner.tick()
```

That's all you need for simple tasks. For services with conditional logic (only do something when a condition is met), implement `check()` and `handle()`:

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

runner = Runner()
sensor = TemperatureSensor(threshold=30.0)
runner.add(sensor, period_ms=5000)  # check every 5 seconds


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

## Dependencies

Runner depends on [timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for its tick source and tick arithmetic (`ticks_diff`, `ticks_add`). All three package managers resolve this automatically — just install `chumicro-runner` and timing comes along.

## Platform support

All classes use only basic Python features. Works identically on CPython, MicroPython, and CircuitPython. Designed to be lightweight — uses minimal memory per task, suitable for boards with limited RAM.

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

## Find this library

- **PyPI:** [chumicro-runner](https://pypi.org/project/chumicro-runner/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_runner) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_runner)
- **Source:** [libraries/runner](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner)
