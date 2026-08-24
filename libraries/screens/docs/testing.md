# Testing Helpers

`chumicro_screens.testing` provides `FakePanel`, a panel whose flush performs a configurable number of transfers and counts everything, so an app that owns a `ScreenService` can be driven through whole frames without a display attached.  The module is test support and never lands on a device.

## Usage

```python
from chumicro_screens import ScreenService
from chumicro_screens.testing import FakePanel
from chumicro_timing.testing import FakeTicks

def test_status_page_redraws_once_per_update():
    panel = FakePanel(transfers_per_flush=4)
    screen = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())

    screen.show()
    for tick in range(4):
        screen.handle(tick)

    assert panel.flushes_completed == 1
    assert panel.transfers_completed == 4
```

A frame completes after exactly `transfers_per_flush` calls to `handle()`, mirroring how a real paged driver spreads a frame across ticks.

## Test hooks

| Hook | What it does |
|---|---|
| `transfers_per_flush` | Bus transfers one frame needs; each `handle()` advances one. |
| `fail_on_transfer = N` | Transfer `N` raises `OSError` instead, simulating a bus fault mid-frame. |
| `flushes_started` / `flushes_completed` | Frames begun and frames fully sent. |
| `transfers_completed` | Total transfers across all frames. |

## Using these fakes in your own tests

Install `chumicro-screens` and import the fakes straight into your test suite:

```python
from chumicro_screens.testing import FakePanel
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
