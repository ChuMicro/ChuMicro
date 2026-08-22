# chumicro-buttons

**Buttons that catch the press even when your loop is busy.**

Wire a button to a pin, read `button.just_pressed` in the loop you already wrote, and the press lands whether your program was idle or halfway through a slow network call.  Debouncing, long presses, auto-repeat, and double-click counting come with it, and the same code runs on CircuitPython, MicroPython, and your laptop.

## Quick example

```python
import board
import digitalio
from chumicro_buttons import Button
from chumicro_timing import ticks_ms

button = Button(pin=board.GP14)

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

while True:
    now = ticks_ms()
    button.check(now)

    if button.just_pressed:
        led.value = not led.value
```

`just_pressed` is true for exactly one pass of the loop, so you can read it as often as you like without it firing twice.

## Documentation

- [User Guide](guide.md): wiring a button, debouncing in software and in hardware, long presses and repeats, several keys at once, and wiring into a runner
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): writing button logic as a unit test with `FakeButtonSource`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
