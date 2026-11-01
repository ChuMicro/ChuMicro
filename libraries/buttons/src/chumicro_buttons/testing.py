"""Host-test helper: ``FakeButtonSource``, an edge source a test presses and releases by hand."""

__chumicro_test_support__ = True


class FakeButtonSource:
    """An edge source for host tests, pressed and released by the test in place of a pin.

    Pass it as ``Button(source=FakeButtonSource(), ticks=FakeTicks())``, with ``FakeTicks``
    from ``chumicro_timing.testing``.  Queue edges with ``press`` and ``release``, then call
    the button's ``check(now_ms)``.  Each edge carries its own timestamp, so a test can stamp
    an edge earlier than the tick that collects it, as a real board's capture does.

    Args:
        key_count: How many keys the source reports.  Give a ``Buttons`` or ``KeyMatrix``
            one per key.

    Attributes:
        poll_calls: How many times a button asked the source to capture.
        deinit_calls: How many times a button released the source.
        overflowed: Set it True to report a dropped edge on the next ``check``.
    """

    def __init__(self, key_count: int = 1) -> None:
        self.key_count = key_count
        self.overflowed = False
        self.event_key = 0
        self.event_pressed = False
        self.event_ms = 0
        self.poll_calls = 0
        self.deinit_calls = 0
        self._queued = []

    def press(self, key_index: int = 0, at_ms: int = 0) -> None:
        """Queue a press of key ``key_index`` that happened at tick ``at_ms``."""
        self._queued.append((key_index, True, at_ms))

    def release(self, key_index: int = 0, at_ms: int = 0) -> None:
        """Queue a release of key ``key_index`` that happened at tick ``at_ms``."""
        self._queued.append((key_index, False, at_ms))

    def poll(self, now_ms: int) -> None:
        """Count the call in ``poll_calls``.  The test fills the queue itself."""
        self.poll_calls += 1

    def next_event(self) -> bool:
        """Move the oldest queued edge into ``event_key``, ``event_pressed``, and ``event_ms``.

        Returns:
            True when an edge was moved, False once the queue is empty.
        """
        if not self._queued:
            return False
        key_index, pressed, at_ms = self._queued.pop(0)
        self.event_key = key_index
        self.event_pressed = pressed
        self.event_ms = at_ms
        return True

    def deinit(self) -> None:
        """Count the call in ``deinit_calls``."""
        self.deinit_calls += 1
