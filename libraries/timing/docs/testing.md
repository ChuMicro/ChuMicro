# Testing Helpers

`chumicro_timing.testing` provides deterministic fakes for host-side tests.

## Usage with Rate and Deadline

The value objects take the current time as an explicit `now_ms` argument, so there is nothing to inject — hand them `FakeTicks.ticks_ms()` at construction and on each poll, and use `FakeTicks.advance()` to move time forward:

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
    # The schedule has advanced — polling again at the same time returns False
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

## Usage from other libraries

Libraries that depend on `chumicro-timing` can import `FakeTicks` directly:

```python
# In another library's test file
from chumicro_timing.testing import FakeTicks
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_timing.testing
    options:
      members:
        - FakeTicks

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · [PyPI](https://pypi.org/project/chumicro-timing/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
