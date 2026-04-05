# chumicro-compat

Cross-runtime compatibility polyfills for CPython, MicroPython, and CircuitPython.

Provides lightweight reimplementations of CPython standard-library features that are missing or incomplete on microcontroller runtimes.  On CPython, re-exports the real C implementations for zero overhead.

## Installation

```bash
# CPython (pip)
pip install chumicro-compat

# CircuitPython (circup)
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-compat

# MicroPython (mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat
```

For experimental (pre-release) versions from the develop branch:

```bash
pip install chumicro-compat-experimental
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-compat
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_compat
```

## Quick example

```python
from chumicro_compat.functools import partial


def set_led(pin, brightness):
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

- [User guide](docs/guide.md) — what's polyfilled and why, usage patterns
- [API reference](docs/api.md) — full API documentation

## Examples

| Example | What it shows |
|---|---|
| `partial_basic.py` | Freeze one argument to a function |
| `partial_keyword_override.py` | Freeze keyword args, override at call time |
| `partial_callback.py` | Wire a callback with frozen context (embedded pattern) |
