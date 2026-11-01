# chumicro-compat

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**`functools.partial` for CircuitPython and MicroPython, which leave it out.**

`partial(set_led, 13)` returns a new function with some of its arguments already filled in.  It hands a callback the pin, sensor, or name it should work on, without a global variable or a wrapper function for each one.  With `from chumicro_compat.functools import partial`, the same code runs on CircuitPython, MicroPython, and CPython.

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

## What's included

### functools

| Symbol | Description |
|---|---|
| `partial(func, *args, **keywords)` | Return a new function that calls `func` with these arguments filled in, followed by whatever you pass when you call it |
| `partial.func` | The original function |
| `partial.args` | The filled-in positional arguments, as a tuple |
| `partial.keywords` | The filled-in keyword arguments, as a dict.  A keyword passed at call time replaces the one filled in |

## Where this fits

Needs no other library.  Import it in your own code wherever a board needs `functools.partial`.

## Platform support

| Runtime | What happens |
|---|---|
| CPython | Uses the built-in `functools.partial` |
| MicroPython | Uses a small pure-Python version |
| CircuitPython | Uses a small pure-Python version |

Calling a partial, its `func`, `args`, and `keywords` attributes, and its `repr()` work the same on all three runtimes.

## Examples

| Example | What it shows |
|---|---|
| [`partial_basic.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/compat/examples/partial_basic.py) | Fills in a pin and a label with `partial`, replaces the label in one call, keeps the new functions in a list of callbacks, and fades two pretend LEDs forever |

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
