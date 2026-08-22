# chumicro-knobs

**Rotary encoders and analog knobs, read as a number that holds still.**

Turn a shaft and `encoder.position` counts the clicks.  Turn a potentiometer and `knob.value` lands on a step and stays there.  A fast spin arrives whole even when your loop was busy elsewhere, a parked wiper keeps reporting the same number, and the same code runs on CircuitPython, MicroPython, and your laptop.

## Quick example

```python
import board
from chumicro_knobs import Encoder
from chumicro_timing import ticks_ms

volume = Encoder(board.GP16, board.GP17, bounds=(0, 20))

while True:
    now = ticks_ms()
    volume.check(now)

    if volume.just_moved:
        print("volume", volume.position)
```

`just_moved` is true for exactly one pass of the loop, so you can read it as often as you like without it firing twice.  `bounds` walks the number between 0 and 20 and stops it at both ends.

## Documentation

- [User Guide](guide.md): wiring an encoder, bounds and wrap, reading a potentiometer, the deadband that holds it still, callbacks, and wiring into a runner
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): turning a shaft and parking a wiper from a unit test

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
