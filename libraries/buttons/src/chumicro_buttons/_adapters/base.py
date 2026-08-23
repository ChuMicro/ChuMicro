"""``ButtonSource``: the contract every per-runtime edge source implements."""


class ButtonSource:
    """Contract for the reader that turns hardware into clean, debounced edges.

    A source owns capture and debounce; long press, repeat, and click counting are decided
    above it.  ``next_event()`` publishes an edge on the three ``event_*`` attributes rather
    than returning a tuple, because a tuple per edge would allocate inside the tick loop.
    """

    # Plain class, not a Protocol: MicroPython has no typing module to import.

    #: How many keys this source reports, numbered 0 to ``key_count - 1``.
    key_count = 0

    #: True when capture dropped at least one edge since the flag was last cleared.
    overflowed = False

    #: Which key the current edge belongs to; only valid after ``next_event()`` is True.
    event_key = 0

    #: True when the current edge is a press, False when it is a release.
    event_pressed = False

    #: Tick the current edge happened at, on the same clock the source was given.
    event_ms = 0

    def poll(self, now_ms: int) -> None:
        """Take one capture step, and take ``now_ms`` as the tick this pass is measured from.

        A source that samples reads the hardware here.  A source that debounces while draining
        judges its settle window against ``now_ms`` rather than a clock it reads for itself, so
        every duration in one pass is measured from one instant.
        """
        raise NotImplementedError

    def next_event(self) -> bool:
        """Advance to the next captured edge.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an edge, False
            once the queue is drained for this tick.
        """
        raise NotImplementedError

    def deinit(self) -> None:
        """Release the pins and any interrupt this source installed."""
        raise NotImplementedError
