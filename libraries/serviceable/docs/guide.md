# User Guide

## Overview

`chumicro-serviceable` provides a `ServiceRunner` for tick-based main loops. Its job is simple: **capture `ticks_ms()` once per tick and distribute the shared timestamp** to all registered components.

This ensures every component in your application sees the same moment in time, preventing drift between independent clock reads on slow microcontrollers.

## The shared-timestamp pattern

In a main loop, you should capture `ticks_ms()` once and pass it to everything:

```python
from chumicro_timing import Heartbeat, ticks_ms

led_beat = Heartbeat(period_ms=500)
sensor_beat = Heartbeat(period_ms=5000)

while True:
    now = ticks_ms()
    if led_beat.poll(now):
        toggle_led()
    if sensor_beat.poll(now):
        read_sensor()
```

This works perfectly for simple loops. As your application grows — more heartbeats, network clients, button scanners — the `ServiceRunner` handles the clock and active-component servicing for you.

## Using ServiceRunner

```python
from chumicro_serviceable import ServiceRunner
from chumicro_timing import Heartbeat

led_beat = Heartbeat(period_ms=500)
sensor_beat = Heartbeat(period_ms=5000)

runner = ServiceRunner()

while True:
    now = runner.tick()
    if led_beat.poll(now):
        toggle_led()
    if sensor_beat.poll(now):
        read_sensor()
```

`runner.tick()` captures `ticks_ms()` once and returns the shared timestamp. If any active components are registered (see below), they are serviced before the timestamp is returned.

## Active components

Some components need per-tick work beyond a simple poll — for example, an MQTT client must process incoming data, or a sensor driver must manage sampling state. These components implement `service(now_ms)`:

```python
class TemperatureMonitor:
    def __init__(self, sensor, period_ms):
        self._sensor = sensor
        self._heartbeat = Heartbeat(period_ms)
        self.latest_reading = None

    def service(self, now_ms):
        if self._heartbeat.poll(now_ms):
            self.latest_reading = self._sensor.read()
```

Register them with the runner, and they are serviced automatically on each tick:

```python
temp_monitor = TemperatureMonitor(sensor, period_ms=5000)
runner = ServiceRunner(services=[temp_monitor])

while True:
    now = runner.tick()  # calls temp_monitor.service(now)
    if temp_monitor.latest_reading is not None:
        print(f"Temperature: {temp_monitor.latest_reading}")
```

The contract is duck-typed — no base class or import from `chumicro-serviceable` is required. Any object with a `service(now_ms)` method works.

## Testing

Use `FakeTicks` from `chumicro-timing` for deterministic time, and `FakeService` from this library for verifying that a runner correctly services components:

```python
from chumicro_serviceable import ServiceRunner
from chumicro_serviceable.testing import FakeService
from chumicro_timing.testing import FakeTicks

def test_runner_services_components():
    fake = FakeTicks()
    svc = FakeService()
    runner = ServiceRunner(services=[svc], ticks=fake)

    fake.advance(100)
    runner.tick()

    assert svc.ticks == [100]
```

See the [testing helpers](testing.md) page for details.

## Platform notes

`ServiceRunner` uses only basic Python features. Works identically on CPython, MicroPython, and CircuitPython.
