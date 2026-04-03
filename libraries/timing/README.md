# chumicro-timing

Cross-runtime millisecond tick helpers and periodic timing utilities for CircuitPython, MicroPython, and CPython.

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
from chumicro_timing import Heartbeat

heartbeat = Heartbeat(period_ms=1000)

while True:
    if heartbeat.poll():
        print("one second elapsed")
    # ... do other work ...
```

## What's included

| Symbol | Description |
|---|---|
| `ticks_ms()` | Monotonic millisecond counter, wraps every ~6.2 days |
| `ticks_diff(end, start)` | Wraparound-safe signed difference |
| `ticks_add(ticks, delta)` | Wraparound-safe addition |
| `Heartbeat(period_ms)` | Periodic timer that fires once per elapsed period |

## Platform support

Works identically on:
- **CPython** — uses `time.monotonic_ns` (or `time.monotonic` as fallback)
- **MicroPython** — uses `time.ticks_ms`
- **CircuitPython** — uses `supervisor.ticks_ms` (or `time.ticks_ms`)

## Testing

The `chumicro_timing.testing` module provides `FakeTicks` for deterministic host-side tests:

```python
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
heartbeat = Heartbeat(period_ms=100, ticks=fake)

fake.advance(100)
assert heartbeat.poll() is True
```

## Docs

- [User guide](docs/guide.md) — getting started, usage patterns, platform notes
- [API reference](docs/api.md) — full API documentation
- [Testing helpers](docs/testing.md) — using `FakeTicks` in your tests
