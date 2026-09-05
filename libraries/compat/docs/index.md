---
title: "chumicro-compat: standard-library polyfills for CircuitPython and MicroPython"
---

# chumicro-compat

**Cross-runtime compatibility polyfills for CircuitPython, MicroPython, and CPython, and pins by GPIO number on both device runtimes.**

Lightweight reimplementations of the standard-library pieces CircuitPython and MicroPython leave out. Import the polyfill submodule (`from chumicro_compat.functools import partial`) and the same code runs on all three runtimes: on CPython the real C implementation is re-exported, so the import costs nothing there.  `chumicro_compat.wiring` turns an MCU GPIO number into the runtime's pin or bus object, so one construction block runs on MicroPython and CircuitPython alike.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_compat

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat

# CPython
pip install chumicro-compat
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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

## Documentation

- [User Guide](guide.md): `functools.partial` across runtimes, pins and buses by GPIO number, platform notes, examples
- [API Reference](api.md): `partial` and its `func` / `args` / `keywords` attributes; `digital_output`, `spi_bus`, `i2c_bus`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) · \
[PyPI](https://pypi.org/project/chumicro-compat/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
