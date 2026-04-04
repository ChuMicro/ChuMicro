# Testing Helpers

`chumicro_timing.testing` provides deterministic fakes for host-side tests.

## Usage with Heartbeat

Pass a `FakeTicks` instance as the `ticks` parameter to `Heartbeat`. Then use `FakeTicks.ticks_ms()` to get timestamps for `poll()` and `FakeTicks.advance()` to move time forward:

```python
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks

def test_heartbeat_fires_after_period():
    fake = FakeTicks()
    heartbeat = Heartbeat(period_ms=100, ticks=fake)

    now = fake.ticks_ms()
    assert heartbeat.poll(now) is False

    fake.advance(99)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is False

    fake.advance(1)
    now = fake.ticks_ms()
    assert heartbeat.poll(now) is True
    # Timer has been reset — next poll returns False
    assert heartbeat.poll(now) is False
```

## Usage from other libraries

Libraries that depend on `chumicro-timing` can import `FakeTicks` directly:

```python
# In another library's test file
from chumicro_timing.testing import FakeTicks
```

This follows the project convention from [Decision 0010](https://github.com/chumicro/chumicro/blob/main/plans/decisions/0010-library-testability.md): libraries that expose injectable services ship their own test fakes.

## API Reference

::: chumicro_timing.testing
    options:
      members:
        - FakeTicks
