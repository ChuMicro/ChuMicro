# chumicro-compat

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Stdlib polyfills for the bits CircuitPython and MicroPython skipped.**

Import from `chumicro_compat` instead of the stdlib and your code works everywhere. CPython gets the real C implementation (zero overhead); CircuitPython and MicroPython get a lightweight pure-Python version of the same public API.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_compat

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat

# CPython
pip install chumicro-compat
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

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

| Runtime | What happens |
|---|---|
| CPython | Uses the built-in `functools.partial` directly — zero overhead |
| MicroPython | Lightweight pure-Python replacement |
| CircuitPython | Lightweight pure-Python replacement |

The public API (`.func`, `.args`, `.keywords`, `__call__`, `__repr__`) is identical across all runtimes.

## Where this fits

Leaf: no upstream ChuMicro deps.  It is a standalone polyfill that no chumicro library currently requires; reach for it in your own code when you want stdlib features (`functools.partial`, …) missing from CircuitPython / MicroPython.

## Examples

| Example | What it shows |
|---|---|
| `partial_basic.py` | Freeze one argument to a function |
| `partial_keyword_override.py` | Freeze keyword args, override at call time |
| `partial_callback.py` | Wire a callback with frozen context (embedded pattern) |

## Contributing

Working on `chumicro-compat` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/compat/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/compat/experimental/)**

## Find this library

- **PyPI:** [chumicro-compat](https://pypi.org/project/chumicro-compat/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_compat) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_compat)
- **Source:** [libraries/compat](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
