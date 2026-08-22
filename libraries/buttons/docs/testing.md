# Testing Helpers

`chumicro_buttons.testing` provides `FakeButtonSource`, a hand-driven stand-in for the hardware that produces button edges.  Queue the edges you want, tick the button, and assert on what it made of them.  The module declares `__chumicro_test_support__ = True`, so the deploy filter keeps it on the host and it never lands on a device.

This is the piece that makes button behavior testable at a desk.  A long-press state machine or a double-click menu is ordinary logic, and with a fake source it can be tested without a board, without a switch to wear out, and without waiting in real time.

## Usage

Build the button with `source=` instead of `pin=`, then script the edges:

```python
from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_long_press_arms_the_factory_reset():
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=3000)
    settings = Settings()

    source.press(at_ms=100)
    button.check(100)
    assert not settings.reset_armed

    button.check(3200)               # still held, 3100 ms in
    assert button.just_long_pressed
    settings.arm_reset()
    assert settings.reset_armed
```

The button never reads a clock of its own.  It compares the timestamps you pass to `check()` using the arithmetic you hand it, so the test controls time completely and runs instantly.

## Edges carry their own time

Each queued edge takes an `at_ms` separate from the tick you pass to `check()`.  That gap is the case worth testing: on a real board an edge is captured when it happens and noticed later, so a press at 100 ms seen by a loop that got back at 180 ms has already been held for 80 ms.

```python
source.press(at_ms=100)
button.check(180)
assert button.held_ms == 80        # measured from the edge, not from the tick
```

Writing tests this way means slow-loop behavior is covered on the host, where it is easy to reason about, instead of only on hardware.

## Several keys

Pass `key_count` and address each key by number.  Edges for different keys can be queued for the same tick, which is how a chord is tested:

```python
from chumicro_buttons import Buttons
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def test_both_shoulders_together_opens_the_menu():
    source = FakeButtonSource(key_count=2)
    buttons = Buttons(source=source, ticks=FakeTicks())

    source.press(key_index=0, at_ms=100)
    source.press(key_index=1, at_ms=105)
    buttons.check(120)

    assert buttons[0].pressed and buttons[1].pressed
```

## Testing the noisy case

`FakeButtonSource` carries an `overflowed` flag you can set to rehearse what your program does when a signal is too noisy to capture in full:

```python
source.overflowed = True
button.check(200)
assert button.overflowed
```

A real board raises that flag when a bouncing contact fills the capture buffer.  The [guide](guide.md) covers the wiring that stops it happening.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
