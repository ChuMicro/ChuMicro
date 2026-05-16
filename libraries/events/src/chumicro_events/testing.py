"""Test helpers for libraries that consume chumicro-events.

The bus itself is trivial to substitute in tests — any callable
accepting ``(topic, payload)`` works as a subscriber, and the bus's
own ``handle`` is the natural drain point.  This module ships one
helper that's broadly useful when downstream libraries want to assert
against bus traffic without writing one-off mocks.

Test-support: excluded from every bundle and every product / app /
functional device deploy by the ``__chumicro_test_support__`` marker
below (the on-device unit sweep is the one path that stages it).

Usage::

    from chumicro_events import EventBus
    from chumicro_events.testing import RecordingSubscriber

    bus = EventBus()
    recorder = RecordingSubscriber()
    bus.subscribe("wifi.state", recorder)
    bus.publish("wifi.state", "connected")
    bus.handle(now_ms=0)
    assert recorder.events == [("wifi.state", "connected")]
"""

#: Source bundle / sdist only -- never lands on a device.
__chumicro_test_support__ = True


class RecordingSubscriber:
    """Subscriber that captures dispatched events in a list.

    Implements ``__call__(topic, payload)`` so the instance itself
    acts as the subscriber callable.  Captured events are exposed as
    ``events`` (a list of ``(topic, payload)`` tuples) and can be
    cleared via ``clear()``.

    Args:
        topic_filter: Optional exact-match topic filter.  When set,
            events whose topic does not match are dropped without
            being recorded.  Defaults to ``None`` (record everything).
    """

    def __init__(self, topic_filter: str | None = None) -> None:
        self._topic_filter = topic_filter
        self._events: list = []

    @property
    def events(self) -> list:
        """Captured events as ``(topic, payload)`` tuples."""
        return list(self._events)

    @property
    def topic_filter(self) -> str | None:
        """The currently-active topic filter, or ``None``."""
        return self._topic_filter

    def clear(self) -> None:
        """Drop all recorded events."""
        self._events = []

    def __call__(self, topic: str, payload: object) -> None:
        """Capture the event if the topic filter (if any) matches."""
        if self._topic_filter is not None and topic != self._topic_filter:
            return
        self._events.append((topic, payload))
