# chumicro-charlcd

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**The classic 16x2 character LCD, driven the same way on both device runtimes.**

HD44780 panels behind the ubiquitous PCF8574 I2C backpack (LCM1602 class).  The protocol core is runtime-agnostic behind a one-method transport seam, so the same code runs on CircuitPython, MicroPython, and in host tests that assert real HD44780 commands.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_charlcd

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_charlcd

# CPython
pip install chumicro-charlcd
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
# MicroPython; CircuitPython swaps in CircuitPythonTransport.
from chumicro_charlcd import CharLcd, MicroPythonTransport
from chumicro_compat.wiring import i2c_bus

bus = i2c_bus(0, scl=35, sda=33, frequency=100_000)
lcd = CharLcd(MicroPythonTransport(bus))

lcd.write("hello", row=0)
lcd.write("chumicro", row=1, column=4)
lcd.backlight = False        # lands immediately, no text update needed
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `CharLcd(transport, *, columns=16, rows=2, sleep_ms=None)` | HD44780 protocol against a byte-write transport; any geometry up to 40x4, row addresses derived from `columns` |
| `CharLcd.write(text, *, row=0, column=0)` | Write text at a cell, clipped to the row instead of HD44780's mid-line wrap; code points above 255 raise `ValueError` |
| `CharLcd.clear()` | Blank the panel and home the cursor |
| `CharLcd.backlight` | Assignable backlight state; toggles land immediately |

### Transports

| Symbol | Description |
|---|---|
| `CircuitPythonTransport(i2c, address=0x27)` | PCF8574 on `busio.I2C`, locking per write so sensors share the bus politely |
| `MicroPythonTransport(i2c, address=0x27)` | The same against `machine.I2C` |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_charlcd.testing.RecordingTransport` | Captures every raw backpack byte |
| `chumicro_charlcd.testing.decode_bytes` / `decode_nibbles` | Fold enable-pulse pairs back into HD44780 commands, so tests assert protocol rather than golden byte lists |

## Where this fits

The driver takes any constructed I2C bus of its runtime and imports nothing else.  The examples and quick starts resolve that bus by GPIO number through [`chumicro-compat`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/compat)'s `wiring`, which is why the package declares it.  Sibling display families live in [`chumicro-screens`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) (pixel panels).

## Platform support

Works on CPython (host tests), MicroPython, and CircuitPython.

### Contrast wants 5 V

The backpack's contrast circuit is designed for 5 V; powered from 3V3 most panels show faint or invisible text.  Feed the backpack VCC from the board's 5 V pin (VBUS on USB-powered boards) and adjust the contrast pot; the I2C lines still work from 3.3 V GPIOs on common backpacks.

## Examples

| Example | What it shows |
|---|---|
| [`decoded_traffic.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/charlcd/examples/decoded_traffic.py) | The API against a recording transport with decoded HD44780 traffic, no hardware needed |
| [`micropython_hello_lcd.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/charlcd/examples/micropython_hello_lcd.py) | Two-row hello on MicroPython hardware |
| [`circuitpython_hello_lcd.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/charlcd/examples/circuitpython_hello_lcd.py) | The same hello on CircuitPython hardware |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/charlcd/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/charlcd/experimental/)**

## Find this library

- **PyPI:** [chumicro-charlcd](https://pypi.org/project/chumicro-charlcd/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_charlcd) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_charlcd)
- **Source:** [libraries/charlcd](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/charlcd)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
