# chumicro-timing

Cross-runtime millisecond tick helpers and periodic timing utilities for CircuitPython, MicroPython, and CPython.

All timing is non-blocking — nothing in this library calls `time.sleep()`. Capture `ticks_ms()` once per loop iteration and pass the shared timestamp to `Heartbeat.poll()`.

## Installation

### CircuitPython (circup)

Register the ChuMicro bundle (remove the other channel first if switching):

```bash
circup bundle-remove ChuMicro/ChuMicro-Bundle-Experimental   # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

### MicroPython (mip)

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

### CPython (pip)

```bash
pip install chumicro-timing
```

### Experimental (pre-release) versions

Pre-release builds come from the `develop` branch.  Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing

# CPython
pip install chumicro-timing-experimental
```

## Quick example

```python
from chumicro_timing import Heartbeat, ticks_ms

heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()
    if heartbeat.poll(now):
        print("one second elapsed")
    # ... do other work ...
```

## What's included

### Tick functions

| Symbol | Description |
|---|---|
| `ticks_ms()` | Monotonic millisecond counter, wraps every ~6.2 days |
| `ticks_diff(end, start)` | Wraparound-safe signed difference |
| `ticks_add(ticks, delta)` | Wraparound-safe addition |

### Heartbeat

| Symbol | Description |
|---|---|
| `Heartbeat(period_ms, ticks=None)` | Periodic timer that fires once per elapsed period |
| `Heartbeat.poll(now_ms)` | Returns `True` once per period and advances the timer |
| `Heartbeat.is_due(now_ms)` | Check whether the period has elapsed (without advancing) |
| `Heartbeat.reset(now_ms)` | Restart the timer from the given timestamp |
| `Heartbeat.period_ms` | The configured period (read-only property) |

### Testing

| Symbol | Description |
|---|---|
| `FakeTicks(start_ms=0)` | Deterministic tick source for host-side tests |
| `FakeTicks.advance(amount_ms)` | Move the fake clock forward |

## Platform support

The tick source is selected automatically at import time:

| Priority | Source | Runtime |
|---|---|---|
| 1 | `supervisor.ticks_ms` | CircuitPython 7+ |
| 2 | `time.ticks_ms` | MicroPython, some CircuitPython builds |
| 3 | `time.monotonic_ns` | CPython, some CircuitPython boards |
| 4 | `time.monotonic` | Final fallback (float seconds → int ms) |

All sources are masked to a 2²⁹ ms period, so behavior is identical regardless of which source is used.

## Testing your code

The `chumicro_timing.testing` module provides `FakeTicks` for deterministic host-side tests — no wall-clock waits:

```python
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
heartbeat = Heartbeat(period_ms=100, ticks=fake)

now = fake.ticks_ms()
assert heartbeat.poll(now) is False

fake.advance(100)
now = fake.ticks_ms()
assert heartbeat.poll(now) is True
```

## Docs

- [User guide](docs/guide.md) — getting started, usage patterns, platform notes
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `FakeTicks` in your tests

## Find this library

**PyPI:** [chumicro-timing](https://pypi.org/project/chumicro-timing/)
**Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) (CircuitPython & MicroPython)
**Source:** [ChuMicro/ChuMicro](https://github.com/ChuMicro/ChuMicro) — cross-runtime Python libraries for ESP32, RP2040, and other microcontrollers.

