# chumicro-timing

Cross-runtime millisecond tick helpers and periodic timing utilities for CircuitPython, MicroPython, and CPython.

All timing is non-blocking — nothing in this library calls `time.sleep()`. Capture `ticks_ms()` once per loop iteration and pass the shared timestamp to `Heartbeat.poll()`.

## Installation

```bash
# CPython (pip)
pip install chumicro-timing

# CircuitPython (circup) — coming soon
# circup install chumicro-timing

# MicroPython (mip) — coming soon
# import mip; mip.install("chumicro-timing")
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
