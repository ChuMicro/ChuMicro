# Testing Helpers

`chumicro_knobs.testing` provides `FakeEncoderSource` and `FakeAnalogSource`, hand-driven stand-ins for the hardware a knob reads.  Turn the shaft or park the wiper, tick the knob, and assert on what it made of them.  The module declares `__chumicro_test_support__ = True`, so the deploy filter keeps it on the host and it never lands on a device.

This is the piece that makes knob behavior testable at a desk.  A menu that wraps at the end, a volume figure that stops at 20, a brightness slider that has to hold still while a converter wanders underneath: all of that is ordinary logic, and with a fake source it runs on a laptop, in milliseconds, without a shaft to turn ten thousand times.

## Usage

Build the knob with `source=` instead of pins, then script the movement:

```python
from chumicro_knobs import Encoder
from chumicro_knobs.testing import FakeEncoderSource


def test_the_menu_ring_carries_past_the_last_entry():
    source = FakeEncoderSource()
    menu = Encoder(source=source, bounds=(0, 3), wrap=True)

    source.turn(5)
    menu.check(0)

    assert menu.position == 1
```

`turn()` moves the shaft in whole detents, positive one way and negative the other, which is what the runtime sources publish once they have divided the pulses down.  Nothing here reads a clock: a knob hands the timestamp it was given straight down to its source, so the test decides what time it is and stays instant and deterministic.

A source can also start with a count already on it, standing in for a knob built while the shaft was somewhere other than home:

```python
source = FakeEncoderSource(raw_position=17)
```

The first `check()` treats that as the starting point and reports no movement, so a restart mid-session behaves the way a real board does.

## Turns add up between ticks

Several turns queued before one `check()` arrive together, which is how a test covers the spin that happened while the loop was busy elsewhere:

```python
source.turn(4)
source.turn(3)
volume.check(0)

assert volume.delta == 7
```

That is the case worth writing a test for, because it is the one a fast desk loop never reproduces by itself and a device with a socket read in it hits every day.

## An analog knob with no wiper

`FakeAnalogSource` carries a reading on the same 0 to 65535 scale every runtime reports on.  `set_raw()` parks the wiper, and small moves are how a test proves the deadband is doing its job:

```python
from chumicro_knobs import AnalogKnob
from chumicro_knobs.testing import FakeAnalogSource


def test_a_parked_wiper_holds_the_brightness_step():
    source = FakeAnalogSource()
    brightness = AnalogKnob(source=source)

    source.set_raw(32768)
    brightness.check(0)
    assert brightness.value == 50

    source.set_raw(33168)                       # 400 counts of wander
    assert brightness.check(10) is False        # inside the deadband, so nothing moved
    assert brightness.value == 50
```

Give the knob a `deadband=` of its own to test a tighter or looser setting, and `FakeAnalogSource(raw=...)` to start it somewhere along the sweep.

## What the fakes record

Both fakes keep a tally of what the knob asked of them, so a test can assert on the conversation as well as on the reading:

| Hook | What it holds |
|---|---|
| `source.poll_calls` | How many times the knob asked this source for a reading |
| `source.last_poll_ms` | The tick that last reading was asked for, which proves the knob passes the loop's shared timestamp down rather than fetching a clock of its own |
| `source.deinit_calls` | How many times the knob released the source |

```python
volume.check(250)
assert source.poll_calls == 1
assert source.last_poll_ms == 250
```

The [guide](guide.md) covers what the readings mean once they arrive, and the [API reference](api.md) lists every method on both fakes.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
