# chumicro-charlcd

**The classic 16x2 character LCD, driven the same way on both device runtimes.**

HD44780 panels behind the ubiquitous PCF8574 I2C backpack.  The protocol core is runtime-agnostic behind a one-method transport seam, so the same code runs on CircuitPython, MicroPython, and in host tests that assert real HD44780 commands.

## Quick example

```python
# MicroPython; CircuitPython swaps the two constructor lines.
from chumicro_charlcd import CharLcd, MicropythonTransport
from machine import I2C, Pin

bus = I2C(0, sda=Pin(33), scl=Pin(35))
lcd = CharLcd(MicropythonTransport(bus))

lcd.write("hello", row=0)
lcd.write("chumicro", row=1, column=4)
lcd.backlight = False
```

## Documentation

- [User Guide](guide.md): writing text, geometry, backlight, the transport seam
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): `RecordingTransport` and the traffic decoders

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/charlcd) · \
[PyPI](https://pypi.org/project/chumicro-charlcd/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
