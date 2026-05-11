# Testing Helpers

`chumicro_events.testing` ships subscriber fakes that downstream
libraries and applications can use to assert against bus traffic
without writing one-off mocks.

## RecordingSubscriber

Captures dispatched events in a list for assertions.  The instance
itself is callable — pass it to `bus.subscribe` directly.

```python
from chumicro_events import EventBus
from chumicro_events.testing import RecordingSubscriber


def test_wifi_state_reaches_audit_log():
    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)

    bus.publish("wifi.state", "connected")
    bus.handle(now_ms=0)

    assert recorder.events == [("wifi.state", "connected")]
```

`RecordingSubscriber(topic_filter="wifi.state")` constructs a
filtered recorder — events whose topic doesn't match the filter are
dropped.  Useful when wiring one recorder against `bus.publisher("*")`-
shaped patterns or when a single recorder is shared across many
topics.  Call `clear()` between assertions.

## Verifying handler-error swallowing

A subscriber that raises shouldn't crash `EventBus.handle`.  Inline a
small failing callable when you need to verify this:

```python
from chumicro_events import EventBus
from chumicro_events.testing import RecordingSubscriber


def test_failing_subscriber_does_not_crash_bus():
    bus = EventBus()

    def boom(topic, payload):
        raise RuntimeError("subscriber boom")

    survivor = RecordingSubscriber()
    bus.subscribe("topic", boom)
    bus.subscribe("topic", survivor)

    bus.publish("topic", "x")
    bus.handle(now_ms=0)

    assert bus.handler_errors == 1
    assert survivor.events == [("topic", "x")]
```

## Usage from other libraries

Libraries that depend on `chumicro-events` can import the fakes directly:

```python
from chumicro_events.testing import RecordingSubscriber
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_events.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/events) · \
[PyPI](https://pypi.org/project/chumicro-events/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
