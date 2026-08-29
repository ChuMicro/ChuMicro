# User Guide

## Overview

The LCM1602-class module is the cheapest, most bin-common display there is: an HD44780 character LCD behind a PCF8574 I2C backpack.  `CharLcd` speaks the HD44780 protocol against a one-method transport seam (`write_byte(value)`), so the core never imports a bus API; `CircuitPythonTransport` and `MicropythonTransport` are the two shipped seam implementations, and tests drive the same core with a recorder.  Initialization runs the datasheet's mode-forcing sequence, so it recovers from any state, including a warm MCU reboot against a still-configured panel.

## Getting started

```python
# MicroPython
from chumicro_charlcd import CharLcd, MicropythonTransport
from machine import I2C, Pin

bus = I2C(0, sda=Pin(33), scl=Pin(35))
lcd = CharLcd(MicropythonTransport(bus))
lcd.write("hello", row=0)
```

```python
# CircuitPython
import board, busio
from chumicro_charlcd import CharLcd, CircuitPythonTransport

bus = busio.I2C(board.IO35, board.IO33)  # SCL, SDA
lcd = CharLcd(CircuitPythonTransport(bus))
lcd.write("hello", row=0)
```

Construction blocks about 60 ms for the panel's power-on settle and mode forcing.

## Writing text

`write(text, row=..., column=...)` positions the cursor and sends the characters.  Text is clipped to the row rather than wrapped: the HD44780's native wrap lands mid-line on the other row and never reads as intended.  Positions outside the panel geometry raise `ValueError`.

```python
lcd.write("temp 21.5C", row=0)
lcd.write("fan", row=1, column=6)
lcd.clear()
```

## Panel geometry

The default is 16x2.  The row address table also covers 20x4 panels with the same class:

```python
lcd = CharLcd(transport, columns=20, rows=4)
lcd.write("row three", row=2)
```

## Backlight

`backlight` is an assignable property.  The bit rides in every bus byte, and assigning sends one data-less write so the change lands immediately rather than at the next text update:

```python
lcd.backlight = False
lcd.backlight = True
```

## The transport seam

A transport is any object with `write_byte(value)` putting one raw byte on the PCF8574.  The shipped transports take an already-constructed bus, so the library imports no hardware modules; the CircuitPython one locks around every byte so display traffic interleaves politely with sensors on a shared bus.  A custom backpack address (solder jumpers, or the 0x3F A-suffix parts) passes at construction:

```python
transport = MicropythonTransport(bus, address=0x3F)
```

## Timing

The controller's busy flag is never read; timed waits are simpler, universal, and the datasheet numbers are generous.  `clear()` sleeps 2 ms, the one genuinely slow command.  Each character costs four I2C writes (two nibbles, two enable states), so a full 16-character row is 68 bus transactions; on a 100 kHz bus budget roughly 10 ms for a full-row rewrite and keep per-tick updates short.  The PCF8574 is a Standard-mode 100 kHz part, so headroom comes from writing fewer cells rather than from a faster bus.  The `sleep_ms` constructor seam injects a recorder in tests so nothing actually waits.

## Testing

`chumicro_charlcd.testing` ships `RecordingTransport` plus decoders that fold enable-pulse pairs back into HD44780 commands, so downstream tests assert protocol rather than golden byte lists:

```python
from chumicro_charlcd import CharLcd
from chumicro_charlcd.testing import RecordingTransport, decode_bytes

transport = RecordingTransport()
lcd = CharLcd(transport, sleep_ms=[].append)
del transport.raw[:]

lcd.write("Hi", row=1)
assert decode_bytes(transport.raw)[0] == (0, 0x80 | 0x40)
```

[Testing Helpers](testing.md) covers the full surface.

## Platform notes

The core and both transports run on CPython, MicroPython, and CircuitPython; nothing in the library imports a hardware module, so host tests exercise the identical code the device runs.  One hardware note: the backpack's contrast circuit wants 5 V on VCC; from 3V3 most panels are faint or blank.

The two runtimes disagree on bus speed.  `busio.I2C` defaults to 100 kHz, which the PCF8574 is rated for; `machine.I2C` defaults to 400 kHz on rp2, which it is not.  Pass `freq=100_000` when constructing a MicroPython bus.  Backpacks vary on whether they populate the SDA and SCL pull-ups, and a board relying on the MCU's internal pull-ups will not clock reliably above 100 kHz; 4.7 kΩ to 3V3 on each line fixes it.

## Examples

| Example | What it shows |
|---|---|
| [`decoded_traffic.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/charlcd/examples/decoded_traffic.py) | The API against a recording transport with decoded HD44780 traffic, no hardware needed |
| [`micropython_hello_lcd.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/charlcd/examples/micropython_hello_lcd.py) | Two-row hello on MicroPython hardware |
| [`circuitpython_hello_lcd.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/charlcd/examples/circuitpython_hello_lcd.py) | The same hello on CircuitPython hardware |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/charlcd) · \
[PyPI](https://pypi.org/project/chumicro-charlcd/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
