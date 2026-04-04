# Testing Helpers

`chumicro_serviceable.testing` provides `FakeEventSink` for verifying that your components emit the right events in host-side tests — no ring buffer capacity limits, no dispatch overhead.

## Usage with a component

Pass a `FakeEventSink` as the `event_sink` argument to `service()`:

```python
from chumicro_serviceable.testing import FakeEventSink
from chumicro_timing import Heartbeat
from chumicro_timing.testing import FakeTicks


class PeriodicReporter:
    EVENT_REPORT = "reporter.report"

    def __init__(self, period_ms, ticks=None):
        self._heartbeat = Heartbeat(period_ms=period_ms, ticks=ticks)

    def service(self, event_sink, now_ms):
        if self._heartbeat.poll(now_ms):
            event_sink.emit(self, self.EVENT_REPORT)


def test_reporter_emits_on_period():
    fake_ticks = FakeTicks()
    reporter = PeriodicReporter(period_ms=100, ticks=fake_ticks)
    sink = FakeEventSink()

    # Not due yet — no events.
    reporter.service(sink, fake_ticks.ticks_ms())
    assert len(sink.events) == 0

    # Advance past the period.
    fake_ticks.advance(100)
    reporter.service(sink, fake_ticks.ticks_ms())
    assert len(sink.events) == 1
    assert sink.events[0].event_type == "reporter.report"
```

## Inspecting events

`FakeEventSink.events` is a plain list of `Event` objects.  Each event has `source`, `event_type`, and `data` attributes:

```python
event = sink.events[0]
assert event.source is reporter
assert event.event_type == "reporter.report"
assert event.data is None
```

## Clearing between tests

Call `clear()` to reset the sink between test phases:

```python
sink.clear()
assert len(sink.events) == 0
```

## Usage from other libraries

Libraries that implement the serviceable pattern can import `FakeEventSink` directly:

```python
# In another library's test file
from chumicro_serviceable.testing import FakeEventSink
```

This follows the project convention from [Decision 0010](https://github.com/chumicro/chumicro/blob/main/plans/decisions/0010-library-testability.md): libraries that expose injectable services ship their own test fakes.

## API Reference

::: chumicro_serviceable.testing
    options:
      members:
        - FakeEventSink
