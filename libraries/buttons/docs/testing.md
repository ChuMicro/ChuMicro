# Testing Helpers

`chumicro_buttons.testing` holds `FakeButtonSource`, a stand-in for the pin hardware that captures button edges.  A test queues presses and releases on it, ticks the button, and checks what the button made of them, with no board, no switch, and no waiting.  `pip install chumicro-buttons pytest` installs everything the tests on this page import.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_reset_button.py` and run `pytest test_reset_button.py`:

```python
from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_holding_three_seconds_is_a_long_press():
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=3000)

    source.press(at_ms=100)
    button.check(100)
    assert button.pressed
    assert not button.just_long_pressed

    button.check(3100)
    assert button.just_long_pressed
```

`Button` takes `source=` in place of a pin.  It reads no clock of its own: the `now_ms` passed to `check()` is the time, so the test decides when three seconds have passed.

## `FakeButtonSource`

| Call or attribute | What it does |
|---|---|
| `FakeButtonSource(key_count=1)` | Reports `key_count` keys: 1 for a `Button`, more for a `Buttons`. |
| `press(key_index=0, at_ms=0)` | Queues a press of key `key_index`, stamped `at_ms`. |
| `release(key_index=0, at_ms=0)` | Queues a release of key `key_index`, stamped `at_ms`. |
| `overflowed` | Set to `True` to rehearse a signal too noisy to capture in full.  The next `check()` copies it to the button and clears it. |
| `poll_calls` | Counts the times the button asked the source to capture. |
| `deinit_calls` | Counts the times the button released the source. |

Each edge carries its own `at_ms`, separate from the tick passed to `check()`.  A board stamps each edge when it happens.  The loop notices it later, so a press at 100 ms seen by a loop that got back at 180 ms has been held for 80 ms:

```python
from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_hold_time_counts_from_the_edge():
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks())

    source.press(at_ms=100)
    button.check(180)

    assert button.held_ms == 80
```

`key_count` and `key_index` address the keys of a `Buttons`.  Edges for two keys queued before one tick arrive together, which is how a test covers a chord:

```python
from chumicro_buttons import Buttons
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_both_shoulder_buttons_together():
    source = FakeButtonSource(key_count=2)
    buttons = Buttons(source=source, ticks=FakeTicks())

    source.press(key_index=0, at_ms=100)
    source.press(key_index=1, at_ms=105)
    buttons.check(120)

    assert buttons.keys[0].pressed
    assert buttons.keys[1].pressed
```

`overflowed` rehearses what a program does when a bouncing contact fills a board's capture buffer.  The [guide](guide.md) covers the wiring that prevents it.

```python
from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_the_button_reports_a_dropped_edge():
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks())

    source.overflowed = True
    button.check(200)

    assert button.overflowed
    assert source.poll_calls == 1
```

## API reference

The [API page](api.md#chumicro_buttonstesting) lists every method on `FakeButtonSource`.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
