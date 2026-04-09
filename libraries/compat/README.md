# chumicro-compat

Cross-runtime compatibility polyfills for CircuitPython, MicroPython, and CPython.

Provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on microcontroller runtimes.  On CPython, re-exports the real C implementations for zero overhead.

## Installation

### CircuitPython (circup)

Register the ChuMicro bundle (remove the other channel first if switching):

```bash
circup bundle-remove ChuMicro/ChuMicro-Bundle-Experimental   # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-compat
```

### MicroPython (mip)

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat
```

### CPython (pip)

```bash
pip install chumicro-compat
```

### Experimental (pre-release) versions

Pre-release builds are published automatically when a library version is bumped.  Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-compat

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_compat

# CPython
pip install chumicro-compat-experimental
```

## Quick example

```python
from chumicro_compat.functools import partial

def set_led(pin: int, brightness: int) -> None:
    """Set an LED pin to a brightness level."""
    print(f"pin {pin} → {brightness}%")

# Freeze the pin, vary the brightness later.
set_status_led = partial(set_led, 13)
set_status_led(50)   # pin 13 → 50%
set_status_led(100)  # pin 13 → 100%
```

## What's included

### functools

| Symbol | Description |
|---|---|
| `partial(func, *args, **keywords)` | Freeze positional and keyword arguments to a callable |
| `partial.func` | The original wrapped callable |
| `partial.args` | Frozen positional arguments (tuple) |
| `partial.keywords` | Frozen keyword arguments (dict) |

## Platform support

| Runtime | Implementation |
|---|---|
| CPython | Re-exports the C-implemented `functools.partial` directly |
| MicroPython | Pure-Python polyfill with `__slots__` |
| CircuitPython | Pure-Python polyfill with `__slots__` |

The public API (`.func`, `.args`, `.keywords`, `__call__`, `__repr__`) is identical across all runtimes.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/compat/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/compat/experimental/)**

Browse on GitHub:

- [User guide](docs/guide.md) — what's polyfilled and why, usage patterns
- [API reference](docs/api.md) — full API documentation

## Examples

| Example | What it shows |
|---|---|
| `partial_basic.py` | Freeze one argument to a function |
| `partial_keyword_override.py` | Freeze keyword args, override at call time |
| `partial_callback.py` | Wire a callback with frozen context (embedded pattern) |

## Find this library

**PyPI:** [chumicro-compat](https://pypi.org/project/chumicro-compat/)
**Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) (CircuitPython & MicroPython)
**Source:** [ChuMicro/ChuMicro](https://github.com/ChuMicro/ChuMicro) — cross-runtime Python libraries for ESP32, RP2040, and other microcontrollers.
