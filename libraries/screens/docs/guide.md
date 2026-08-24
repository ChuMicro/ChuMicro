# User Guide

## Overview

A full display frame is often too big to send in one go: a mono OLED frame over I2C takes tens of milliseconds on the bus, which is several ticks' worth of loop time.  `ScreenService` paces the flush instead.  You draw, call `show()`, and the service advances the panel's flush one bounded bus transfer per tick, with a frame-rate floor so redraws never crowd out buttons, network, or sensors.  The panel underneath is duck-typed: anything with a `flush()` method that returns an iterator works.

## Getting started

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

The first two passes each perform one transfer; the rest of the loop stays free.

## The panel protocol

A panel is any object with one method:

```python
def flush(self):
    """Return an iterator; each advance performs one bounded bus transfer."""
```

Write it as a generator: do a transfer, `yield`, do the next.  A frame with N transfers completes after N `handle()` calls.  The shapes that come up:

```python
class PagedPanel:
    """A frame in pages, one page per tick: the usual driver shape."""
    def flush(self):
        for page_index in range(8):
            if page_index > 0:
                yield
            self._write_page(page_index)

class SingleTransferPanel:
    """A frame small enough for one transfer, done in one tick."""
    def flush(self):
        self._write_frame()
        return
        yield

class BackgroundRefreshPanel:
    """The runtime refreshes in the background; flush just requests it."""
    def flush(self):
        self._request_refresh()
        return
        yield
```

The trailing `return` / `yield` pair keeps the method a generator while yielding zero times, so the whole flush lands in one `handle()`.

Keep each transfer bounded: one page, strip, or window per advance, sized so a single advance stays inside a few milliseconds on your bus.

## Pacing and the frame-rate floor

`refresh_interval_ms` is a floor between flush starts, counted from each start.  The default of 50 caps redraws at 20 frames per second; `0` starts a new flush on the first tick after every `show()`.

Two behaviors worth knowing:

- `show()` during an active flush marks the *next* frame.  The current frame always finishes; the fresh content flushes after the floor elapses.
- A panel error mid-flush propagates out of `handle()` and drops that frame.  The service goes idle; the next `show()` schedules a fresh flush.

## Runner pattern

`ScreenService` implements `check(now_ms)` / `handle(now_ms)`, so it registers like any other service, and `next_deadline(now_ms)` lets `runner.wait()` sleep until the next flush is actually due:

```python
from chumicro_runner import Runner
from chumicro_screens import ScreenService
from chumicro_timing import ticks_ms

runner = Runner()
screen = ScreenService(panel)
runner.add(screen)

while True:
    now_ms = ticks_ms()
    runner.tick()
    runner.wait(now_ms)
```

Draw and `show()` from any other handler; the screen service flushes on its own turns.

## Memory notes

Idle ticks allocate nothing: `check()` is comparisons only.  Starting a frame allocates one generator; the cost is per frame, not per tick, and only when `show()` was called.

## Testing

`chumicro_screens.testing.FakePanel` counts flush starts, transfers, and completions, and can inject a bus fault mid-frame:

```python
from chumicro_screens import ScreenService
from chumicro_screens.testing import FakePanel
from chumicro_timing.testing import FakeTicks

panel = FakePanel(transfers_per_flush=4)
screen = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())

screen.show()
for tick in range(4):
    screen.handle(tick)

assert panel.flushes_completed == 1
```

[Testing Helpers](testing.md) covers the full hook set.

## Platform notes

The service behaves identically on CPython, MicroPython, and CircuitPython.  Panel drivers are where the runtimes differ: a MicroPython framebuf driver pages its frame across advances, while a CircuitPython displayio panel refreshes in the background and its flush is a single advance.  Hardware drivers are added per controller as each passes bench validation.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass, simulated on CPython |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
