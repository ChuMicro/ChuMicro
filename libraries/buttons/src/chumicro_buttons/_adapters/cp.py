"""CircuitPython edge sources: the firmware ``keypad`` scan, plus a polled fallback."""

__chumicro_runtimes__ = ("circuitpython",)

from chumicro_buttons._adapters.base import ButtonSource

#: How many ``keypad`` scans a key holds its new state for before an edge is believed.
#: Sampling the settle window four times is what makes ``settle_ms`` a quiet period
#: rather than just a scan rate: a bounce shorter than the window never survives four
#: scans running, while one scan per window would believe the first sample that moved.
SCANS_PER_SETTLE_WINDOW = 4

#: Shortest scan interval worth asking ``keypad`` for, in seconds.  Its background scan
#: rides a 1024 Hz tick, so anything under a millisecond buys no extra resolution.
MINIMUM_SCAN_INTERVAL_SECONDS = 0.001


def keypad_scan_timing(settle_ms: int) -> tuple[float, int]:
    """Return the ``interval`` and ``debounce_threshold`` that spend ``settle_ms``.

    ``keypad`` emits an edge once a key has held its new state for
    ``debounce_threshold`` scans, and consecutive scans are ``interval`` seconds
    apart, so the settle window is the product of the two.  Splitting the window
    into four scans keeps the background scan cheap when the window is long, and
    still rejects every bounce shorter than the window.  A window too short to
    split scans as fast as the runtime resolves and counts what fits.

    Args:
        settle_ms: Quiet period a raw signal must hold before an edge is believed.
            Zero trusts the signal as it arrives.

    Returns:
        ``(interval_seconds, debounce_threshold)`` for a ``keypad`` scanner.
    """
    if settle_ms <= 0:
        return MINIMUM_SCAN_INTERVAL_SECONDS, 1
    if settle_ms < SCANS_PER_SETTLE_WINDOW:
        scans = int(settle_ms)
        return MINIMUM_SCAN_INTERVAL_SECONDS, scans if scans >= 1 else 1
    return settle_ms / SCANS_PER_SETTLE_WINDOW / 1000, SCANS_PER_SETTLE_WINDOW


class _KeypadScanSource(ButtonSource):  # pragma: no cover - CP runtime path
    """Drain shared by the two firmware scanners, which queue identical events.

    ``keypad.Keys`` and ``keypad.KeyMatrix`` differ only in how they read the pins.
    Both publish an ``EventQueue`` of key transitions, so taking events off that
    queue and publishing them on the ``event_*`` attributes is written once here.
    """

    def _adopt_scanner(self, scanner: object, event: object) -> None:
        """Take ownership of a running ``keypad`` scanner.

        Args:
            scanner: A ``keypad.Keys`` or ``keypad.KeyMatrix`` already constructed.
            event: A ``keypad.Event`` reused for every edge, so draining the queue
                allocates nothing.
        """
        self._scanner = scanner
        self._events = scanner.events
        self._event = event
        self.key_count = scanner.key_count
        # Start from "every key released" so a key already held when the program
        # starts is reported as a press instead of never being noticed.
        scanner.reset()

    def poll(self, now_ms: int) -> None:
        """Do nothing: ``keypad`` scans and debounces the pins in the runtime's own
        background tick, so anything that happened is already queued by the time
        this tick runs.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        return None

    def next_event(self) -> bool:
        """Take the next transition off the ``keypad`` queue.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an edge,
            False once the queue is drained for this tick.
        """
        events = self._events
        event = self._event
        if events.get_into(event):
            self.event_key = event.key_number
            self.event_pressed = event.pressed
            # keypad stamps every event from supervisor.ticks_ms, which is the
            # domain chumicro_timing publishes, so the value carries across as-is.
            self.event_ms = event.timestamp
            return True
        if events.overflowed:
            self.overflowed = True
            # clear() is the only way to put the flag back, and it costs nothing
            # here because the queue just reported itself empty.
            events.clear()
        return False

    def deinit(self) -> None:
        """Stop the background scan and release the pins it held."""
        self._scanner.deinit()


class CpButtonSource(_KeypadScanSource):  # pragma: no cover - CP runtime path
    """Edges for keys wired one to a pin, captured by ``keypad.Keys``.

    The firmware scans and debounces in C between passes of the loop, so a tap that
    starts and ends inside one pass still arrives, stamped with the tick it happened
    on rather than the tick that noticed it.

    A build compiled without ``keypad`` falls back to sampling ``digitalio`` pins once
    per ``poll(now_ms)``.  That fallback reports only what the pins read when the loop
    looked, so a tap between two passes is lost; it exists for the few boards that
    switch the module off, since ``keypad`` otherwise tracks a build flag that is on by
    default.

    Args:
        pins: Runtime pin objects, one per key.
        active_low: True when a pressed key reads low, the wiring an internal pull-up
            gives.
        settle_ms: Quiet period a raw signal must hold before an edge is believed.
    """

    def __init__(self, pins: object, *, active_low: bool, settle_ms: int) -> None:
        try:
            import keypad
        except ImportError:
            self._scanner = None
            self._start_polled(pins, active_low=active_low, settle_ms=settle_ms)
            return
        self._pin_inputs = None
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

    def poll(self, now_ms: int) -> None:
        """Sample the pins when this source is the polled fallback, otherwise do
        nothing because the firmware scan already captured the tick's edges.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        pin_inputs = self._pin_inputs
        if pin_inputs is None:
            return None
        pending = self._pending
        believed = self._believed
        change_ms = self._change_ms
        pressed_value = self._pressed_value
        key_index = 0
        key_count = self.key_count
        while key_index < key_count:
            sample = 1 if pin_inputs[key_index].value == pressed_value else 0
            if sample != pending[key_index]:
                pending[key_index] = sample
                if sample != believed[key_index]:
                    change_ms[key_index] = now_ms
            key_index += 1
        self._sample_ms = now_ms
        return None

    def next_event(self) -> bool:
        """Advance to the next edge, from the ``keypad`` queue or from the samples the
        fallback took.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an edge,
            False once this tick has no more.
        """
        if self._pin_inputs is None:
            return super().next_event()
        pending = self._pending
        believed = self._believed
        change_ms = self._change_ms
        ticks_diff = self._ticks_diff
        settle_ms = self._settle_ms
        sample_ms = self._sample_ms
        key_index = self._sweep_key
        key_count = self.key_count
        while key_index < key_count:
            if (
                pending[key_index] != believed[key_index]
                and ticks_diff(sample_ms, change_ms[key_index]) >= settle_ms
            ):
                believed[key_index] = pending[key_index]
                self.event_key = key_index
                self.event_pressed = pending[key_index] == 1
                self.event_ms = change_ms[key_index]
                self._sweep_key = key_index + 1
                return True
            key_index += 1
        self._sweep_key = 0
        return False

    def deinit(self) -> None:
        """Stop the scan, or release the fallback's pins."""
        pin_inputs = self._pin_inputs
        if pin_inputs is None:
            super().deinit()
            return
        key_index = 0
        while key_index < len(pin_inputs):
            pin_inputs[key_index].deinit()
            key_index += 1

    def _start_polled(self, pins: object, *, active_low: bool, settle_ms: int) -> None:
        """Configure ``digitalio`` inputs and the per-key state their samples feed.

        Args:
            pins: Runtime pin objects, one per key.
            active_low: True when a pressed key reads low.
            settle_ms: Quiet period a raw signal must hold before an edge is believed.
        """
        import array

        import digitalio
        from chumicro_timing.ticks import ticks_diff, ticks_ms

        self._ticks_diff = ticks_diff
        self._settle_ms = settle_ms
        self._pressed_value = not active_low
        pull = digitalio.Pull.UP if active_low else digitalio.Pull.DOWN

        inputs = []
        for pin in pins:
            pin_input = digitalio.DigitalInOut(pin)
            pin_input.direction = digitalio.Direction.INPUT
            pin_input.pull = pull
            inputs.append(pin_input)
        self._pin_inputs = tuple(inputs)
        self.key_count = len(self._pin_inputs)

        # believed starts at "released" for every key while pending starts at what the
        # pin actually reads, so a key held at startup arrives as a press.
        self._pending = array.array("b", [0] * self.key_count)
        self._believed = array.array("b", [0] * self.key_count)
        self._change_ms = array.array("i", [0] * self.key_count)
        self._sweep_key = 0
        self._sample_ms = ticks_ms()
        key_index = 0
        while key_index < self.key_count:
            if self._pin_inputs[key_index].value == self._pressed_value:
                self._pending[key_index] = 1
            self._change_ms[key_index] = self._sample_ms
            key_index += 1


class CpKeyMatrixSource(_KeypadScanSource):  # pragma: no cover - CP runtime path
    """Edges for a keypad wired as rows by columns, captured by ``keypad.KeyMatrix``.

    Keys are numbered row-major, ``row * len(column_pins) + column``, which is the
    numbering the firmware scanner already uses.

    The diodes decide which way the scan runs.  With their anodes on the columns, a row
    is driven low while it is scanned and a pressed key pulls its column low against a
    pull-up; with them the other way round the whole scan inverts.

    Args:
        row_pins: Runtime pin objects for the rows.
        column_pins: Runtime pin objects for the columns.
        columns_to_anodes: True when the diode anodes sit on the column pins.
        settle_ms: Quiet period a raw signal must hold before an edge is believed.
    """

    def __init__(
        self,
        row_pins: object,
        column_pins: object,
        *,
        columns_to_anodes: bool = True,
        settle_ms: int,
    ) -> None:
        import keypad

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
