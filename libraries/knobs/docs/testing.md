# Testing Helpers

`chumicro_knobs.testing` holds two stand-ins for the hardware a knob reads.  `FakeEncoderSource` replaces the quadrature pins of a rotary encoder, and `FakeAnalogSource` replaces the analog pin under a potentiometer.  A test turns the shaft or parks the wiper, ticks the knob, and checks what the knob made of it, with no board and no waiting.  `pip install chumicro-knobs pytest` installs everything the tests on this page import.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_menu_knob.py` and run `pytest test_menu_knob.py`:

```python
from chumicro_knobs import Encoder
from chumicro_knobs.testing import FakeEncoderSource


def test_menu_wraps_past_the_last_entry():
    source = FakeEncoderSource()
    menu = Encoder(source=source, bounds=(0, 3), wrap=True)

    source.turn(5)
    menu.check(0)

    assert menu.position == 1
```

`Encoder` takes `source=` in place of its two pins.  A knob reads no clock: it hands the `now_ms` passed to `check()` straight to its source.

## `FakeEncoderSource`

| Call or attribute | What it does |
|---|---|
| `FakeEncoderSource(raw_position=0)` | Starts the shaft count at `raw_position` detents. |
| `turn(detents)` | Turns the shaft by whole detents, negative for the other direction. |
| `raw_position` | The shaft count so far. |
| `poll_calls` | Counts the times the knob asked for a reading. |
| `last_poll_ms` | The `now_ms` of the latest reading, which shows the knob passes its tick down. |
| `deinit_calls` | Counts the times the knob released the source. |

Several turns before one `check()` arrive together, the way a fast spin does while the loop is busy elsewhere:

```python
from chumicro_knobs import Encoder
from chumicro_knobs.testing import FakeEncoderSource


def test_turns_between_ticks_add_up():
    source = FakeEncoderSource()
    volume = Encoder(source=source)

    source.turn(4)
    source.turn(3)
    volume.check(250)

    assert volume.delta == 7
    assert source.poll_calls == 1
    assert source.last_poll_ms == 250
```

An `Encoder` takes the source's count at construction as its zero.  `raw_position` stands in for a knob built while the shaft sat somewhere other than home:

```python
from chumicro_knobs import Encoder
from chumicro_knobs.testing import FakeEncoderSource


def test_a_knob_counts_from_where_the_shaft_sat():
    source = FakeEncoderSource(raw_position=17)
    knob = Encoder(source=source)

    knob.check(0)
    assert knob.position == 0

    source.turn(2)
    knob.check(10)
    assert knob.position == 2
```

## `FakeAnalogSource`

| Call or attribute | What it does |
|---|---|
| `FakeAnalogSource(raw=0)` | Starts the reading at `raw`, on the 0 to 65535 scale every runtime reports. |
| `set_raw(raw)` | Parks the wiper at `raw`. |
| `raw` | The current reading. |
| `poll_calls` | Counts the times the knob asked for a conversion. |
| `last_poll_ms` | The `now_ms` of the latest conversion. |
| `deinit_calls` | Counts the times the knob released the source. |

A small move tests the deadband, the band of wander an `AnalogKnob` ignores:

```python
from chumicro_knobs import AnalogKnob
from chumicro_knobs.testing import FakeAnalogSource


def test_a_parked_wiper_holds_its_step():
    source = FakeAnalogSource()
    brightness = AnalogKnob(source=source)

    source.set_raw(32768)
    brightness.check(0)
    assert brightness.value == 50

    source.set_raw(33168)
    assert brightness.check(10) is False
    assert brightness.value == 50
```

The second reading sits 400 counts from the first, inside the default deadband of 512, so `check()` reports no movement.  `AnalogKnob(deadband=...)` sets a tighter or looser band.

## API reference

The [API page](api.md#chumicro_knobstesting) lists every method on both fakes.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
