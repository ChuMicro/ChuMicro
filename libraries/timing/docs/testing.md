# Testing Helpers

`chumicro_timing.testing` provides `FakeTicks`, a hand-driven clock that only moves when you tell it to, plus a `sleep_ms` shim for host code that really does want to block.  The module declares itself test support, so the deploy walker and the bundle builder drop it and it never lands on a microcontroller.

## Usage with Rate and Deadline

The value objects take the current time as an explicit `now_ms` argument, so there is nothing to inject.  Hand them `FakeTicks.ticks_ms()` at construction and on each poll, then use `FakeTicks.advance()` to move time forward:

```python
from chumicro_timing import Rate
from chumicro_timing.testing import FakeTicks

def test_rate_fires_after_period() -> None:
    """Rate fires exactly when the period elapses."""
    fake = FakeTicks()
    rate = Rate(100, fake.ticks_ms())

    assert rate.due(fake.ticks_ms()) is False

    fake.advance(99)
    assert rate.due(fake.ticks_ms()) is False

    fake.advance(1)
    assert rate.due(fake.ticks_ms()) is True
    # The schedule has advanced, so polling again at the same time returns False.
    assert rate.due(fake.ticks_ms()) is False
```

A `Deadline` is driven the same way:

```python
from chumicro_timing import Deadline
from chumicro_timing.testing import FakeTicks

def test_deadline_expires() -> None:
    """Deadline expires once the timeout elapses."""
    fake = FakeTicks()
    deadline = Deadline(100, fake.ticks_ms())

    assert deadline.expired(fake.ticks_ms()) is False
    assert deadline.remaining(fake.ticks_ms()) == 100

    fake.advance(100)
    assert deadline.expired(fake.ticks_ms()) is True
    assert deadline.remaining(fake.ticks_ms()) == 0
```

`FakeTicks` also answers `sleep_ms(duration_ms)` by advancing itself, so a `Runner` built with `ticks=FakeTicks()` idles instantly instead of stalling your test suite.

## Using these fakes in your own tests

Your test suite imports the fake straight from the installed package, the same way this library's own tests do:

```python
from chumicro_timing.testing import FakeTicks
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_timing.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
