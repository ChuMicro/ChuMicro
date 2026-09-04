# chumicro-screens

**Display flushing that never stalls your loop.**

Draw the frame, call `show()`, and the flush crosses the bus one bounded transfer per tick, with a frame-rate floor so redraws don't monopolize the loop.

## Quick example

```python
from chumicro_screens import ScreenService
from chumicro_timing import ticks_ms

class ConsolePanel:
    """Pretend driver: one print stands in for one bus transfer."""
    def __init__(self):
        self.message = ""
    def flush(self):
        print("transfer 1:", self.message[:8])
        yield
        print("transfer 2:", self.message[8:])

panel = ConsolePanel()
screen = ScreenService(panel, refresh_interval_ms=50)
panel.message = "hello screens"
screen.show()

for loop_pass in range(4):
    now_ms = ticks_ms()
    if screen.check(now_ms):
        screen.handle(now_ms)
```

## Documentation

- [User Guide](guide.md): pacing a flush, the panel protocol, the GC9A01A and SSD1306 drivers on both runtimes, wiring into a runner
- [API Reference](api.md): every public class and method, generated from the source docstrings
- [Testing Helpers](testing.md): using `FakePanel` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
