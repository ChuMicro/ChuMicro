---
title: "chumicro-compat: functools.partial for CircuitPython and MicroPython"
---

# chumicro-compat

**`functools.partial` for CircuitPython and MicroPython, which leave it out.**

`partial(set_led, 13)` returns a new function with some of its arguments already filled in.  It hands a callback the pin, sensor, or name it should work on, without a global variable or a wrapper function for each one.  With `from chumicro_compat.functools import partial`, the same code runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_compat

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_compat

# CPython
pip install chumicro-compat
```

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Make one function per LED, then fade both pretend LEDs up and down forever:

```python
import time

from chumicro_compat.functools import partial


def set_led(pin, brightness, label="LED"):
    print(f"{label} on pin {pin}: {brightness}%")


# set_status_led(50) now runs set_led(13, 50, label="status LED").
set_status_led = partial(set_led, 13, label="status LED")
set_power_led = partial(set_led, 2, label="power LED")
leds = [set_status_led, set_power_led]

brightness = 0
step = 25
while True:
    for set_brightness in leds:
        set_brightness(brightness)

    brightness += step
    if brightness == 0 or brightness == 100:
        step = -step

    time.sleep(0.5)
```

## Documentation

- [User Guide](guide.md): filling in positional and keyword arguments, callbacks, the `func` / `args` / `keywords` attributes, and platform notes
- [API Reference](api.md): `partial` and its `func` / `args` / `keywords` attributes

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat) · \
[PyPI](https://pypi.org/project/chumicro-compat/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
