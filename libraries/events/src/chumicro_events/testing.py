"""Test-support fakes for asserting against EventBus delivery."""

__chumicro_test_support__ = True


class RecordingSubscriber:
    """Test fake: appends every ``(topic, payload)`` delivered for later inspection."""

    def __init__(self, topic_filter: str | None = None) -> None:
        """Builds a recorder that keeps every delivery, or only those matching ``topic_filter``.

        Args:
            topic_filter: When set, deliveries on other topics are dropped instead of recorded.
        """
        self._topic_filter = topic_filter
        self._events: list = []

    @property
    def events(self) -> list:
        """Returns a fresh copy of the recorded ``(topic, payload)`` tuples in arrival order."""
        return list(self._events)

    @property
    def topic_filter(self) -> str | None:
        """Reports the topic this recorder is pinned to, or ``None`` when it accepts every topic."""
        return self._topic_filter

    def clear(self) -> None:
        """Discards every recorded event so the next assertion starts from empty."""
        self._events = []

    def __call__(self, topic: str, payload: object) -> None:
        if self._topic_filter is not None and topic != self._topic_filter:
            return
        self._events.append((topic, payload))
