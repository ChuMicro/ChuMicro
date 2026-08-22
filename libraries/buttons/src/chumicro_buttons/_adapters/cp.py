"""CircuitPython edge sources: discrete keys and a grid, both scanned by ``keypad``."""

__chumicro_runtimes__ = ("circuitpython",)

from chumicro_buttons._adapters.base import ButtonSource

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

#: How many ``keypad`` scans a key holds its new state for before an edge is believed.  Four
#: samples per window make ``settle_ms`` a quiet period rather than a scan rate: a bounce
#: shorter than the window never survives four scans running.
SCANS_PER_SETTLE_WINDOW = const(4)

#: Shortest scan interval worth asking ``keypad`` for, in seconds.  Its background scan
#: rides a 1024 Hz tick, so anything under a millisecond buys no extra resolution.
MINIMUM_SCAN_INTERVAL_SECONDS = 0.001


def keypad_scan_timing(settle_ms: int) -> tuple[float, int]:
    """Return the ``keypad`` ``(interval_seconds, debounce_threshold)`` that spend ``settle_ms``.

    ``keypad`` emits an edge once a key has held its new state for ``debounce_threshold``
    scans ``interval`` seconds apart, so the settle window is the product of the two.  A
    ``settle_ms`` of zero, or one too short to split four ways, scans as fast as the runtime
    resolves and counts what fits.
    """
    if settle_ms <= 0:
        return MINIMUM_SCAN_INTERVAL_SECONDS, 1
    if settle_ms < SCANS_PER_SETTLE_WINDOW:
        scans = int(settle_ms)
        return MINIMUM_SCAN_INTERVAL_SECONDS, scans if scans >= 1 else 1
    return settle_ms / SCANS_PER_SETTLE_WINDOW / 1000, SCANS_PER_SETTLE_WINDOW


def keypad_module() -> object:
    """Return the firmware ``keypad`` module, or refuse and say what to do about it.

    Raises:
        RuntimeError: when the running build has no ``keypad`` module.
    """
    try:
        import keypad
    except ImportError:
        # keypad rides a build flag that is on by default, and the boards that leave it off
        # are smaller than the RAM and flash this library is written for.
        raise RuntimeError(
            "this CircuitPython build has no keypad module, which is what scans the "
            "keys.  Flash a full build of CircuitPython for this board, or build the "
            "keys with source=FakeButtonSource(...) from chumicro_buttons.testing and "
            "drive them yourself.",
        ) from None
    return keypad  # pragma: no cover - CP runtime path


class _KeypadScanSource(ButtonSource):  # pragma: no cover - CP runtime path
    """Drain shared by the two firmware scanners, which queue identical events.

    ``keypad.Keys`` and ``keypad.KeyMatrix`` differ only in how they read the pins, and both
    publish an ``EventQueue`` of key transitions, so the drain is written once here.
    """

    def _adopt_scanner(self, scanner: object, event: object) -> None:
        """Take ownership of a constructed ``keypad.Keys`` or ``keypad.KeyMatrix``.

        ``event`` is one ``keypad.Event`` reused for every edge, so draining allocates nothing.
        """
        self._scanner = scanner
        self._events = scanner.events
        self._event = event
        self.key_count = scanner.key_count
        # Start from "every key released" so a key already held when the program starts is
        # reported as a press instead of never being noticed.
        scanner.reset()

    def poll(self, now_ms: int) -> None:
        """Do nothing: ``keypad`` scans on the runtime's own background tick, so anything that
        happened is already queued by the time this tick runs.
        """
        return None

    def next_event(self) -> bool:
        """Take the next transition off the ``keypad`` queue.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an edge, False
            once the queue is drained for this tick.
        """
        events = self._events
        event = self._event
        if events.get_into(event):
            self.event_key = event.key_number
            self.event_pressed = event.pressed
            # keypad stamps every event from supervisor.ticks_ms, the same wrap-safe
            # millisecond domain the caller's clock reports, so no conversion is needed.
            self.event_ms = event.timestamp
            return True
        if events.overflowed:
            self.overflowed = True
            # clear() is the only way to put the flag back, and it costs nothing here
            # because the queue just reported itself empty.
            events.clear()
        return False

    def deinit(self) -> None:
        """Stop the background scan and release the pins it held."""
        self._scanner.deinit()


class CpButtonSource(_KeypadScanSource):  # pragma: no cover - CP runtime path
    """Edges for keys wired one to a pin, captured by ``keypad.Keys``.

    The firmware scans and debounces in C between passes of the loop, so a tap that starts and
    ends inside one pass still arrives, stamped with the tick it happened on rather than the
    tick that noticed it.  ``active_low`` is True for a key wired to ground behind a pull-up.
    """

    def __init__(self, pins: object, *, active_low: bool, settle_ms: int) -> None:
        keypad = keypad_module()

        interval_seconds, debounce_threshold = keypad_scan_timing(settle_ms)
        self._adopt_scanner(
            keypad.Keys(
                pins,
                value_when_pressed=not active_low,
                interval=interval_seconds,
                debounce_threshold=debounce_threshold,
            ),
            keypad.Event(),
        )


class CpKeyMatrixSource(_KeypadScanSource):  # pragma: no cover - CP runtime path
    """Edges for a keypad wired as rows by columns, captured by ``keypad.KeyMatrix``.

    Keys are numbered row-major, ``row * len(column_pins) + column``.  With the diode anodes
    on the columns a row is driven low while it is scanned and a pressed key pulls its column
    low against a pull-up; ``columns_to_anodes=False`` inverts the whole scan.
    """

    def __init__(
        self,
        row_pins: object,
        column_pins: object,
        *,
        columns_to_anodes: bool = True,
        settle_ms: int,
    ) -> None:
        keypad = keypad_module()

        interval_seconds, debounce_threshold = keypad_scan_timing(settle_ms)
        self._adopt_scanner(
            keypad.KeyMatrix(
                row_pins,
                column_pins,
                columns_to_anodes=columns_to_anodes,
                interval=interval_seconds,
                debounce_threshold=debounce_threshold,
            ),
            keypad.Event(),
        )
