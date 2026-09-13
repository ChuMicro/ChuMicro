# chumicro-compat

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Stdlib polyfills for the bits CircuitPython and MicroPython skipped, and pins by GPIO number on both.**

Import the polyfill submodule (`from chumicro_compat.functools import partial`) instead of the stdlib module and your code works everywhere. CPython gets the real C implementation (zero overhead); CircuitPython and MicroPython get a lightweight pure-Python version of the same public API.  `chumicro_compat.wiring` turns an MCU GPIO number into the runtime's pin or bus object, so one construction block runs on both device runtimes.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_compat

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat

# CPython
pip install chumicro-compat
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

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

### wiring

| Symbol | Description |
|---|---|
| `digital_output(gpio, value=0)` | Callable output pin: `pin(1)` drives high, `pin(0)` low, `pin()` reads back |
| `spi_bus(controller, sck=, mosi=, miso=None, baudrate=, polarity=, phase=)` | The runtime's SPI bus on those GPIO numbers |
| `i2c_bus(controller, scl=, sda=, frequency=400_000)` | The runtime's I2C bus on those GPIO numbers |

```python
from chumicro_compat.wiring import digital_output, spi_bus

spi = spi_bus(0, sck=6, mosi=7, baudrate=40_000_000)
chip_select = digital_output(5, value=1)   # same numbers on MicroPython and CircuitPython
```

The runtime's own pin object is accepted in place of a number, and an already-constructed bus passes through unchanged.

## Where this fits

Leaf: no upstream ChuMicro deps.  No chumicro library requires it; reach for it in your own code when you want a stdlib feature (`functools.partial`) missing from CircuitPython / MicroPython, or when one app should construct its pins and buses the same way on both device runtimes.

## Platform support

| Runtime | `functools.partial` | `wiring` |
|---|---|---|
| CPython | Uses the built-in `functools.partial` directly, zero overhead | Raises `RuntimeError`; inject a fake |
| MicroPython | Lightweight pure-Python replacement | `machine.Pin`, `machine.SPI`, `machine.I2C` |
| CircuitPython | Lightweight pure-Python replacement | `digitalio.DigitalInOut` behind a callable, `busio.SPI`, `busio.I2C` |

The `partial` API (`.func`, `.args`, `.keywords`, `__call__`, `__repr__`) is identical across all runtimes, and a GPIO number resolves to the same wire on both device runtimes.

## Examples

| Example | What it shows |
|---|---|
| `partial_basic.py` | Freeze one argument to a function |
| `partial_keyword_override.py` | Freeze keyword args, override at call time |
| `partial_callback.py` | Wire a callback with frozen context (embedded pattern) |
| `blink.py` | Blink GPIO15 from one file that runs on both device runtimes |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/compat/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/compat/experimental/)**

## Find this library

- **PyPI:** [chumicro-compat](https://pypi.org/project/chumicro-compat/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_compat) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_compat)
- **Source:** [libraries/compat](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
