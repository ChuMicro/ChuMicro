# chumicro-screens

**Pixel panels with no frame in RAM and no tick on the bus.**

Describe a scene of items, mark what changed, and the flush paints the strips those changes touch into one small buffer and sends each as one bus transfer per tick, on MicroPython and CircuitPython from one app file.

## Quick example

```python
from chumicro_screens import Rect, Screen, ScreenService, Text
from chumicro_screens.testing import FakeScreenPanel
from chumicro_timing import ticks_ms

panel = FakeScreenPanel(width=32, height=32, rows=8)   # any panel: a strip and write_strip()
screen = Screen(panel)
service = ScreenService(screen, refresh_interval_ms=50)

label = Text(2, 12, "hi", 1)
screen.add(Rect(0, 0, 32, 32, 0))
screen.add(label)
service.show()

for loop_pass in range(6):
    now_ms = ticks_ms()
    if service.check(now_ms):
        service.handle(now_ms)    # one strip per pass; the loop stays live
print(panel.writes)               # [(0, 8), (8, 8), (16, 8), (24, 8)]
```

## Documentation

- [User Guide](guide.md): the scene and its items, the GC9A01A and SSD1306 panels, proportional fonts, writing a panel, pacing, wiring into a runner
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): using `FakeScreenPanel` and `FakePanel` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
