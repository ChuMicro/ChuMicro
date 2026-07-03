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
dropped.  Useful when one recorder is subscribed to several topics but
a test only wants to assert on one topic's traffic.  Call `clear()`
between assertions.

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

## Usage from an application

An application that wires an `EventBus` into its own services imports the fake directly to assert on event traffic:

```python
from chumicro_events.testing import RecordingSubscriber
```

No other ChuMicro library depends on `chumicro-events`; the fake is for application and bus tests. Project convention: a library that exposes injectable services ships its own test fakes alongside the production code.

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
