"""``ButtonSource``: the contract every per-runtime edge source implements."""


class ButtonSource:
    """Duck-typed contract for the thing that turns hardware into clean edges.

    A source owns capture and debounce.  It never owns meaning: long press,
    repeat, and click counting all live in :class:`~chumicro_buttons.core.Button`
    so they behave identically on every runtime.

    Draining is allocation-free by design.  ``next_event()`` advances an internal
    cursor and reports whether an edge is available; the edge itself is published
    on the three ``event_*`` attributes rather than returned as a tuple, because a
    tuple per edge would allocate inside the tick loop.

    A concrete source implements ``poll(now_ms)``, ``next_event()``, and
    ``deinit()``, and keeps the attributes below current.
    """

    # Plain class, not a Protocol: MicroPython has no typing module to import.

    #: How many keys this source reports, numbered 0 to ``key_count - 1``.
    key_count = 0

    #: True when capture dropped at least one edge since the flag was last cleared.
    #: Mirrors ``keypad.EventQueue.overflowed`` so it means one thing everywhere.
    overflowed = False

    #: Which key the current edge belongs to; only valid after ``next_event()`` is True.
    event_key = 0

    #: True when the current edge is a press, False when it is a release.
    event_pressed = False

    #: Tick the current edge happened at, in the ``chumicro_timing.ticks_ms`` domain.
    event_ms = 0

    def poll(self, now_ms: int) -> None:
        """Take one capture step, and take the tick this pass is measured against.

        Sources that sample (a matrix scan, an injected fake) read the hardware here.
        Sources backed by a background scan or an interrupt captured their edges
        elsewhere, and have only ``now_ms`` to take: a source that debounces while
        draining judges its settle window against the value handed in here, never
        against a clock it reads for itself, so every duration in one pass of the loop
        is measured from one instant.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        raise NotImplementedError

    def next_event(self) -> bool:
        """Advance to the next captured edge.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an
            edge, False once the queue is drained for this tick.
        """
        raise NotImplementedError

    def deinit(self) -> None:
        """Release the pins and any interrupt this source installed."""
        raise NotImplementedError
