# Testing Helpers

`chumicro_timing.testing` holds `FakeTicks`, a stand-in for the board's millisecond clock.  `FakeTicks` moves only when the test moves it, so a test covering a 30-second timeout finishes in milliseconds.  `pip install chumicro-timing` puts the module on the laptop.  Project deploys and the board bundles leave it out.

## The smallest test

Save this as `test_light_timer.py` and run `pytest test_light_timer.py`:

```python
from chumicro_timing import Deadline
from chumicro_timing.testing import FakeTicks


def test_light_turns_off_after_five_seconds():
    clock = FakeTicks()
    timer = Deadline(5000, clock.ticks_ms())

    clock.advance(4999)
    assert not timer.expired(clock.ticks_ms())

    clock.advance(1)
    assert timer.expired(clock.ticks_ms())
```

`Deadline` and `Rate` take the current tick as an argument, so the test hands them `clock.ticks_ms()` and decides what time it is.

## `FakeTicks`

`FakeTicks` answers the same `ticks_ms()`, `ticks_diff()`, and `ticks_add()` calls as the board clock.  Any class that takes a `ticks=` argument accepts it.

| Call | What it does |
|---|---|
| `FakeTicks(start_ms=0)` | Starts the clock at `start_ms`. |
| `advance(amount_ms)` | Moves the clock forward by `amount_ms`. |
| `ticks_ms()` | Returns the current reading.  The reading wraps to 0 after `2**29 - 1`, the same point a board's counter wraps. |
| `ticks_diff(end, start)` | Returns `end - start`, correct across the wrap. |
| `ticks_add(ticks, delta)` | Returns `ticks + delta`, wrapped into range. |
| `sleep_ms(duration_ms)` | Moves the clock forward by `duration_ms` and returns at once.  A `Runner` built with `ticks=FakeTicks()` therefore idles without stalling the test. |

A `Rate` driven by `FakeTicks` shows each step of its schedule:

```python
from chumicro_timing import Rate
from chumicro_timing.testing import FakeTicks


def test_rate_fires_once_per_period():
    clock = FakeTicks()
    rate = Rate(100, clock.ticks_ms())

    clock.advance(99)
    assert rate.due(clock.ticks_ms()) is False

    clock.advance(1)
    assert rate.due(clock.ticks_ms()) is True
    assert rate.due(clock.ticks_ms()) is False
```

`start_ms` sets the clock just short of the wrap, which is how a test checks that a timer survives it:

```python
from chumicro_timing import Deadline
from chumicro_timing.testing import FakeTicks


def test_deadline_survives_the_counter_wrap():
    clock = FakeTicks(start_ms=2**29 - 50)
    timer = Deadline(100, clock.ticks_ms())

    clock.advance(99)
    assert clock.ticks_ms() < 100
    assert not timer.expired(clock.ticks_ms())

    clock.advance(1)
    assert timer.expired(clock.ticks_ms())
```

## `sleep_ms`

`chumicro_timing.testing.sleep_ms(duration_ms)` really sleeps.  It calls `time.sleep_ms` where the runtime has one and `time.sleep` otherwise, for a script on the laptop that needs a real pause.

## API reference

::: chumicro_timing.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
