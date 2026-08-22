"""Test-support helpers: a hand-driven :class:`FakeButtonSource`."""

__chumicro_test_support__ = True


class FakeButtonSource:
    """Edge source a test drives by hand instead of by hardware.

    Queue the edges you want the button to see, then tick the button.  Each edge
    carries its own timestamp, which is how a test exercises the case that matters
    on a real board: an edge captured earlier than the tick that noticed it.

        source = FakeButtonSource()
        button = Button(source=source, ticks=FakeTicks())
        source.press(at_ms=100)
        button.check(120)
        assert button.just_pressed

    Args:
        key_count: How many keys this source reports.
    """

    def __init__(self, key_count: int = 1) -> None:
        self.key_count = key_count
        self.overflowed = False
        self.event_key = 0
        self.event_pressed = False
        self.event_ms = 0
        #: How many times the button asked this source to capture.
        self.poll_calls = 0
        #: How many times the button released this source.
        self.deinit_calls = 0
        self._queued = []

    def press(self, key_index: int = 0, at_ms: int = 0) -> None:
        """Queue a press edge for ``key_index`` stamped at ``at_ms``."""
        self._queued.append((key_index, True, at_ms))

    def release(self, key_index: int = 0, at_ms: int = 0) -> None:
        """Queue a release edge for ``key_index`` stamped at ``at_ms``."""
        self._queued.append((key_index, False, at_ms))

    def poll(self, now_ms: int) -> None:
        """Record that a capture step was asked for; the queue is filled by the test."""
        self.poll_calls += 1

    def next_event(self) -> bool:
        """Advance to the next queued edge, or report the queue drained."""
        if not self._queued:
            return False
        key_index, pressed, at_ms = self._queued.pop(0)
        self.event_key = key_index
        self.event_pressed = pressed
        self.event_ms = at_ms
        return True

    def deinit(self) -> None:
        """Record that the button released this source."""
        self.deinit_calls += 1
