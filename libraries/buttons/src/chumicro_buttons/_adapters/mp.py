"""MicroPython edge sources: a capture interrupt for discrete pins, a polled matrix scan."""

__chumicro_runtimes__ = ("micropython",)

import array

from chumicro_buttons._adapters.base import ButtonSource

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

#: Edges the capture ring holds before it starts dropping them.  A cheap tact switch can
#: chatter out a dozen edges per transition, and a press plus a release is two of those
#: bursts; thirty-two slots hold both with room over, at six bytes a slot.
DEFAULT_RING_DEPTH = const(32)


class _KeyEdgeCapture:  # pragma: no cover - MP runtime path
    """The interrupt handler for one pin, holding the key number that pin belongs to.

    One of these is built per pin at construction, so ``record`` already knows which key
    fired and no callable is built per edge.
    """

    def __init__(self, source: object, key_index: int) -> None:
        self._source = source
        self._key_index = key_index

    def record(self, pin: object) -> None:
        """Hand this pin's key number and current level to the capture ring."""
        self._source._capture_edge(self._key_index, pin.value())


class MpButtonSource(ButtonSource):  # pragma: no cover - MP runtime path
    """Edges for keys wired one to a pin, captured by a pin interrupt.

    MicroPython has no background key scanner, so this source installs one ``Pin.irq`` per key
    and lets it record every edge into a ring ``ring_depth`` slots deep.  Debouncing, timing,
    and every callback happen later on the shared tick, in normal context, so a tap that starts
    and ends between two passes of the loop still arrives stamped with the tick it happened on
    and no user code ever runs in interrupt context.  A full ring drops the newest edge and
    raises ``overflowed``, and the next drain re-reads the pins, so the loss costs one wrong
    tick rather than a key that reads pressed for good.

    Args:
        ticks: The clock this source judges by, ``chumicro_timing.ticks`` or anything shaped
            like it.  Required: every settle window is measured against it and every captured
            edge is stamped from it, and there is no other clock here.
    """

    def __init__(
        self,
        pins: object,
        *,
        active_low: bool,
        settle_ms: int,
        ticks: object,
        ring_depth: int = DEFAULT_RING_DEPTH,
    ) -> None:
        from machine import Pin

        self._ticks = ticks
        # The clock's own ticks_ms, bound here so the interrupt handler reaches it in one
        # attribute load and builds nothing on the way.
        self._ticks_ms = ticks.ticks_ms
        self._settle_ms = settle_ms
        self._pressed_level = 0 if active_low else 1

        pull = Pin.PULL_UP if active_low else Pin.PULL_DOWN
        for pin in pins:
            pin.init(Pin.IN, pull)
        self._pins = tuple(pins)
        self.key_count = len(self._pins)

        self._ring_depth = ring_depth
        self._edge_codes = array.array("H", [0] * ring_depth)
        self._edge_times = array.array("i", [0] * ring_depth)
        self._write_index = 0
        self._read_index = 0
        # Created here, before the interrupts attach, so an overflow in the handler rebinds
        # an attribute that already exists instead of growing the instance dict.
        self.overflowed = False
        #: Set when the ring drops an edge, so the next drain re-reads the pins.  It is
        #: separate from ``overflowed``, which the caller clears every tick.
        self._dropped_edges = False

        # believed is what this source has published so far and pending is the last raw level
        # it saw.  While the two disagree the signal is away from the published level, and
        # change_ms says since when, which serves as both the settle test and the timestamp
        # the edge is finally published with.
        self._believed = array.array("b", [0] * self.key_count)
        self._pending = array.array("b", [0] * self.key_count)
        self._change_ms = array.array("i", [0] * self.key_count)
        self._sweep_key = 0

        # believed starts at "released" for every key while pending starts at what the pin
        # actually reads, so a key held at startup arrives as a press.
        started_ms = self._ticks_ms()
        self._now_ms = started_ms
        key_index = 0
        while key_index < self.key_count:
            if self._pins[key_index].value() == self._pressed_level:
                self._pending[key_index] = 1
            self._change_ms[key_index] = started_ms
            key_index += 1

        self._captures = []
        trigger = Pin.IRQ_RISING | Pin.IRQ_FALLING
        key_index = 0
        while key_index < self.key_count:
            capture = _KeyEdgeCapture(self, key_index)
            self._captures.append(capture)
            self._pins[key_index].irq(handler=capture.record, trigger=trigger)
            key_index += 1

    def poll(self, now_ms: int) -> None:
        """Take ``now_ms`` as the tick the drain will judge its settle windows against.

        There is nothing to sample, because the pin interrupt already captured every edge as it
        happened.  What this pass still owes the drain is the one instant it measures against.
        """
        self._now_ms = now_ms
        return None

    def next_event(self) -> bool:
        """Advance to the next debounced edge the interrupt captured.

        Captured edges are folded in the order they arrived, so a press and its release both
        survive even when they landed inside one pass of the loop.  An edge is published once
        the signal has stayed away for ``settle_ms``, stamped with the moment it left rather
        than the moment that became certain.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an edge, False
            once this tick has no more.
        """
        codes = self._edge_codes
        times = self._edge_times
        believed = self._believed
        pending = self._pending
        change_ms = self._change_ms
        ticks_diff = self._ticks.ticks_diff
        settle_ms = self._settle_ms
        pressed_level = self._pressed_level
        ring_depth = self._ring_depth
        read_index = self._read_index

        while read_index != self._write_index:
            code = codes[read_index]
            at_ms = times[read_index]
            read_index += 1
            if read_index >= ring_depth:
                read_index = 0
            self._read_index = read_index
            key_index = code >> 1
            sample = 1 if (code & 1) == pressed_level else 0
            if sample == pending[key_index]:
                continue
            departed = pending[key_index]
            departed_ms = change_ms[key_index]
            confirmed = (
                departed != believed[key_index]
                and ticks_diff(at_ms, departed_ms) >= settle_ms
            )
            pending[key_index] = sample
            if not confirmed:
                # Either the signal came back before its window closed, which makes the
                # excursion bounce, or this is the first step away and the window for it
                # starts here.
                if sample != believed[key_index]:
                    change_ms[key_index] = at_ms
                continue
            # The signal held its new level for a whole window, so publish it.  This edge is
            # the signal leaving again, which starts the next window.
            believed[key_index] = departed
            change_ms[key_index] = at_ms
            self.event_key = key_index
            self.event_pressed = departed == 1
            self.event_ms = departed_ms
            return True

        key_count = self.key_count
        now_ms = self._now_ms
        if self._dropped_edges:
            # A dropped edge can leave pending describing a level the pin has since left,
            # which would report a key as held for good.  Re-reading the pins costs one wrong
            # tick instead, and matches what a level scanner does.
            self._dropped_edges = False
            pins = self._pins
            key_index = 0
            while key_index < key_count:
                sample = 1 if pins[key_index].value() == pressed_level else 0
                if sample != pending[key_index]:
                    pending[key_index] = sample
                    if sample != believed[key_index]:
                        change_ms[key_index] = now_ms
                key_index += 1

        key_index = self._sweep_key
        while key_index < key_count:
            if (
                pending[key_index] != believed[key_index]
                and ticks_diff(now_ms, change_ms[key_index]) >= settle_ms
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
        """Detach every interrupt, then let go of the pins."""
        pins = self._pins
        key_index = 0
        while key_index < len(pins):
            pins[key_index].irq(handler=None)
            key_index += 1
        self._pins = ()
        self._captures = []
        self._dropped_edges = False

    def _capture_edge(self, key_index: int, level: int) -> None:
        """Store one raw edge in the ring.  Runs in interrupt context.

        Nothing here allocates and nothing here decides: the ring takes the key number, the
        level the pin read, and the tick it read it, and working out which edges were bounce
        happens on the drain.  A full ring drops this edge and raises ``overflowed``, so the
        newest edge is the one lost and the flag says a loss happened.
        """
        write_index = self._write_index
        next_write = write_index + 1
        if next_write >= self._ring_depth:
            next_write = 0
        if next_write == self._read_index:
            self.overflowed = True
            self._dropped_edges = True
            return
        self._edge_codes[write_index] = (key_index << 1) | level
        # Reading the clock here is the one place this source may: an interrupt has no tick
        # to be handed, and stamping the edge as it fires is the whole reason the interrupt
        # exists.  It is still the caller's clock, bound at construction so this stays one
        # attribute load.  Everything that judges a duration uses the tick poll took.
        self._edge_times[write_index] = self._ticks_ms()
        self._write_index = next_write


class MpKeyMatrixSource(ButtonSource):  # pragma: no cover - MP runtime path
    """Edges for a keypad wired as rows by columns, read by a polled scan.

    Each ``poll(now_ms)`` drives one row at a time and reads every column, which is the only
    way to tell which key of a shared row and column is down.  An interrupt on a column would
    fire for rows the scan is not driving and report keys nobody touched, so a matrix is polled
    on purpose rather than as a fallback, and what that costs is a tap that starts and ends
    between two passes of the loop.  Keys are numbered row-major,
    ``row * len(column_pins) + column``, and ``columns_to_anodes=False`` inverts the scan for a
    grid whose diodes face the other way.

    Args:
        ticks: The clock this scan judges by, ``chumicro_timing.ticks`` or anything shaped like
            it.  Required: every settle window is measured against it, and there is no other
            clock here.
    """

    def __init__(
        self,
        row_pins: object,
        column_pins: object,
        *,
        columns_to_anodes: bool = True,
        settle_ms: int,
        ticks: object,
    ) -> None:
        from machine import Pin

        self._ticks = ticks
        self._pin_type = Pin
        self._settle_ms = settle_ms
        # A diode only conducts toward its cathode, so the side the anodes sit on picks which
        # level a scanned row drives and which level a pressed key shows up as.
        self._drive_level = 0 if columns_to_anodes else 1
        self._rest_pull = Pin.PULL_UP if columns_to_anodes else Pin.PULL_DOWN

        for pin in row_pins:
            pin.init(Pin.IN, self._rest_pull)
        self._rows = tuple(row_pins)
        for pin in column_pins:
            pin.init(Pin.IN, self._rest_pull)
        self._columns = tuple(column_pins)

        self.key_count = len(self._rows) * len(self._columns)
        self._believed = array.array("b", [0] * self.key_count)
        self._pending = array.array("b", [0] * self.key_count)
        self._change_ms = array.array("i", [0] * self.key_count)
        self._sweep_key = 0
        # Every key starts agreeing with itself, so no window is open and no reading consults
        # this until the first poll replaces it with that pass's tick.
        self._sample_ms = 0

    def poll(self, now_ms: int) -> None:
        """Drive each row in turn and record what every column read, as of ``now_ms``."""
        rows = self._rows
        columns = self._columns
        pin_type = self._pin_type
        believed = self._believed
        pending = self._pending
        change_ms = self._change_ms
        drive_level = self._drive_level
        rest_level = 1 - drive_level
        rest_pull = self._rest_pull
        row_count = len(rows)
        column_count = len(columns)
        row_index = 0
        while row_index < row_count:
            row = rows[row_index]
            row.init(pin_type.OUT, value=drive_level)
            key_index = row_index * column_count
            column_index = 0
            while column_index < column_count:
                sample = 1 if columns[column_index].value() == drive_level else 0
                if sample != pending[key_index]:
                    pending[key_index] = sample
                    if sample != believed[key_index]:
                        change_ms[key_index] = now_ms
                column_index += 1
                key_index += 1
            # Drive the row back to its resting level before releasing it, so the columns
            # follow at once instead of drifting there on a weak pull and reading as presses
            # on the next row.
            row.init(pin_type.OUT, value=rest_level)
            row.init(pin_type.IN, rest_pull)
            row_index += 1
        self._sample_ms = now_ms
        return None

    def next_event(self) -> bool:
        """Advance to the next key whose reading has held long enough to believe.

        Returns:
            True when ``event_key`` / ``event_pressed`` / ``event_ms`` hold an edge, False
            once this tick has no more.
        """
        believed = self._believed
        pending = self._pending
        change_ms = self._change_ms
        ticks_diff = self._ticks.ticks_diff
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
        """Stop driving the rows and let go of the pins."""
        pin_type = self._pin_type
        rest_pull = self._rest_pull
        rows = self._rows
        row_index = 0
        while row_index < len(rows):
            rows[row_index].init(pin_type.IN, rest_pull)
            row_index += 1
        self._rows = ()
        self._columns = ()
