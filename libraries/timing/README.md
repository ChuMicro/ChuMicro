# chumicro-timing

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Timers that don't freeze your code — your loop keeps running while waiting.**

Capture `ticks_ms()` once per loop, hand it to a `Heartbeat`, and you've got clean periodic timing — no `time.sleep()`, no wraparound bugs. Works on CircuitPython, MicroPython, and CPython.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)

## Installation

### CircuitPython ([circup](https://github.com/adafruit/circup))

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

### MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html))

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
> ```

### CPython (pip)

```bash
pip install chumicro-timing
```

*Just getting started? Skip this — the install commands above are all you need.*

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped.  Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing

# CPython
pip install chumicro-timing-experimental
```

</details>

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
| `ticks_ms()` | Current time in milliseconds — keeps counting even when it wraps around |
| `ticks_diff(end, start)` | Time elapsed between two tick values (handles wraparound correctly) |
| `ticks_add(ticks, delta)` | Add milliseconds to a tick value (handles wraparound correctly) |

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

## Related libraries

For structured task scheduling with multiple services, see [runner](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner). Runner is built on timing — it captures `ticks_ms()` once per tick and dispatches services on a shared timestamp.

## Platform support

You don't need to pick a tick source — the library detects your runtime and uses the best one available:

| Priority | Source | Runtime |
|---|---|---|
| 1 | `supervisor.ticks_ms` | CircuitPython 7+ |
| 2 | `time.ticks_ms` | MicroPython, some CircuitPython builds |
| 3 | `time.monotonic_ns` | CPython, some CircuitPython boards |
| 4 | `time.monotonic` | Final fallback (float seconds → int ms) |

Behavior is identical regardless of which source is used — you don't need to think about this, it just works.

<details>
<summary>Technical detail: tick wraparound</summary>

All sources are masked to a 2²⁹ ms period (~6.2 days). `ticks_diff` and `ticks_add` handle wraparound correctly, so your timers keep working even when the counter rolls over.

</details>

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

## Examples

| Example | What it shows |
|---|---|
| `heartbeat_blink.py` | Basic periodic timer loop |
| `multiple_heartbeats.py` | Multiple heartbeats at different rates |
| `timeout_check.py` | One-shot timeout using `is_due` |
| `debounce.py` | Simulated button debounce |
| `periodic_tick.py` | Manual periodic loop (what Heartbeat does under the hood) |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `circuitpython_debounce.py` | GPIO button debounce on CircuitPython |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `micropython_debounce.py` | GPIO button debounce on MicroPython |

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/timing/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/timing/experimental/)**

## Find this library

- **PyPI:** [chumicro-timing](https://pypi.org/project/chumicro-timing/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_timing) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_timing)
- **Source:** [libraries/timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing)
