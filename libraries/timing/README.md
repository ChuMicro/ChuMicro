# chumicro-timing

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Timers that don't block. Your loop keeps ticking.**

Capture `ticks_ms()` once per loop pass, hand it to a `Heartbeat`, and you've got clean periodic timing on CircuitPython, MicroPython, or CPython. Tick-source detection is automatic, wraparound is handled, and there are no dependencies on anything else in ChuMicro — it's where every other library starts.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython
pip install chumicro-timing
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

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

## Where this fits

Leaf — no upstream ChuMicro deps.  Everything in ChuMicro that owns time depends on it: [`runner`](../runner/), [`sockets`](../sockets/), [`ntp`](../ntp/), [`requests`](../requests/), [`http_server`](../http_server/), [`mqtt`](../mqtt/), [`websockets`](../websockets/).

## Platform support

You don't need to pick a tick source — the library picks the best one available on your runtime. Behavior is identical regardless of which source is used.

| Source | Runtime |
|---|---|
| `supervisor.ticks_ms` | CircuitPython 7+ |
| `time.ticks_ms` | MicroPython, some CircuitPython builds |
| `time.monotonic_ns` | CPython, some CircuitPython boards |
| `time.monotonic` | Final fallback (float seconds → int ms) |

The library tries them top-to-bottom and uses the first one your runtime supports.

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
| `periodic_tick.py` | Manual periodic loop (the same logic `Heartbeat` wraps internally) |
| `circuitpython_blink.py` | LED blink on CircuitPython hardware |
| `circuitpython_debounce.py` | GPIO button debounce on CircuitPython |
| `micropython_blink.py` | LED blink on MicroPython hardware |
| `micropython_debounce.py` | GPIO button debounce on MicroPython |

## Contributing

Working on `chumicro-timing` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/timing/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/timing/experimental/)**

## Find this library

- **PyPI:** [chumicro-timing](https://pypi.org/project/chumicro-timing/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_timing) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_timing)
- **Source:** [libraries/timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
