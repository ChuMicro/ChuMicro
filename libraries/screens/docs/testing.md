# Testing Helpers

`chumicro_screens.testing` provides two fakes.  `FakeScreenPanel` is a panel for a `Screen`: its `strip` records every primitive call with the band the strip held at the time, and `writes` lists every strip sent, so a scene can be driven through whole frames and the asserts read what painted where.  `FakePanel` is a flush-protocol fake for `ScreenService` alone, counting transfers and injecting a bus fault.  The module is test support and never lands on a device.

## Usage

```python
from chumicro_screens import Rect, Screen, ScreenService, Text
from chumicro_screens.testing import FakeScreenPanel
from chumicro_timing.testing import FakeTicks

def test_a_count_change_repaints_its_band_only():
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    service = ScreenService(screen, refresh_interval_ms=0, ticks=FakeTicks())
    count = Text(0, 12, "0", 1)
    screen.add(Rect(0, 0, 32, 32, 0))
    screen.add(count)
    service.show()
    for tick in range(5):
        service.handle(tick)
    del panel.writes[:]

    count.string = "1"
    screen.mark(count)
    service.show()
    for tick in range(5, 8):
        service.handle(tick)

    assert panel.writes == [(8, 8), (16, 8)]
    assert ("text", 8, "1", 0, 12, 1, None) in panel.strip.calls
```

## Test hooks

| Hook | What it does |
|---|---|
| `FakeScreenPanel.writes` | One `(top, count)` pair per strip sent, in order. |
| `FakeScreenPanel.fail_on_write = N` | Write `N` raises `OSError` instead, simulating a bus fault mid-frame. |
| `FakeScreenPanel.strip.calls` | One tuple per primitive call: the name, the strip's `top`, then the arguments. |
| `FakeScreenPanel.strip.prepared` | The rings and texts the strip was asked to prepare at mark time. |
| `FakePanel(transfers_per_flush)` | Bus transfers one frame needs; each `handle()` advances one. |
| `FakePanel.fail_on_transfer = N` | Transfer `N` raises `OSError` instead. |
| `FakePanel.flushes_started` / `flushes_completed` / `transfers_completed` | Frames begun, frames fully sent, and transfers across all frames. |

## Using these fakes in your own tests

Install `chumicro-screens` and import the fakes straight into your test suite:

```python
from chumicro_screens.testing import FakePanel, FakeScreenPanel
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_screens.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens) · \
[PyPI](https://pypi.org/project/chumicro-screens/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
