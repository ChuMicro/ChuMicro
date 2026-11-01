"""``Button`` and ``Buttons``: debounced buttons and switches with long press, repeat, and click counting.

Attributes:
    DEFAULT_SETTLE_MS: The default debounce window, 10 ms: how long a pin must hold a new
        level before the edge counts.  The window is also the shortest press that can
        register.  A tactile switch settles inside a millisecond, a big toggle can bounce
        for 20 ms, and a fast tap can be over in 10.
    DEFAULT_LONG_PRESS_MS: The default hold, 500 ms, before ``just_long_pressed`` fires.
    DEFAULT_REPEAT_DELAY_MS: The default hold, 500 ms, before auto-repeat starts.
"""

import sys

DEFAULT_SETTLE_MS = 10
DEFAULT_LONG_PRESS_MS = 500
DEFAULT_REPEAT_DELAY_MS = 500


def _select_source(pins, *, active_low, settle_ms, ticks):
    """Return the edge source this runtime can build for ``pins``.

    The MicroPython source measures its settle window against ``ticks``; the CircuitPython
    scan debounces in firmware and takes none.
    """
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_buttons._adapters.cp import CpButtonSource
        return CpButtonSource(pins, active_low=active_low, settle_ms=settle_ms)
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_buttons._adapters.mp import MpButtonSource
        return MpButtonSource(pins, active_low=active_low, settle_ms=settle_ms, ticks=ticks)
    raise RuntimeError(
        "CPython has no GPIO to read.  Build the button with "
        "source=FakeButtonSource(...) from chumicro_buttons.testing and drive it "
        "from your test, or run this on CircuitPython or MicroPython.",
    )


class Button:
    """One button or switch, debounced, with long press, auto-repeat, and click counting.

    Call ``check(now_ms)`` once per pass of the loop and read the attributes below.  Or set
    the ``on_`` callbacks and register the button with ``runner.add(button, period_ms=20)``,
    and the runner calls ``handle``, which calls them.  Each ``just_`` attribute is True only
    on the tick its event happened, so several reads in one pass all see it.  A toggle or
    slide switch is a ``Button`` too, and ``pressed`` is its position.

    Built from ``pin``, the button catches edges between ticks, through the firmware
    ``keypad`` scan on CircuitPython and a pin interrupt on MicroPython.  A tap that starts
    and ends between two passes of the loop still registers.

    Args:
        pin: The pin the button is wired to, such as ``board.GP14`` on CircuitPython or
            ``machine.Pin(14)`` on MicroPython.  None for a key that a ``Buttons`` reads.
        ticks: The clock every duration is measured on: ``chumicro_timing.ticks``, or an
            object with the same ``ticks_ms``, ``ticks_add``, and ``ticks_diff``.  The
            ``now_ms`` passed to ``check`` comes from this clock.
        source: A ready-made edge source, used in place of ``pin``.  Tests pass
            ``FakeButtonSource`` from ``chumicro_buttons.testing``.  ``active_low`` and
            ``settle_ms`` then go unused.
        active_low: True when a pressed button reads low, as one wired from the pin to GND
            does.  The pin's internal pull-up is switched on to match.  False switches on
            the pull-down instead, for a button wired to 3V3.
        settle_ms: Debounce window in milliseconds, which is also the shortest press that
            can register.  Raise it for a switch that bounces badly, lower it for fast
            tapping, and use 0 for a button with hardware debouncing.
        long_press_ms: Hold time in milliseconds before ``just_long_pressed`` fires.  0 turns
            long press off.
        repeat_ms: Milliseconds between ``just_repeated`` fires while the button is held.  0
            turns auto-repeat off.
        repeat_delay_ms: Hold time in milliseconds before auto-repeat starts.
        click_ms: Quiet time in milliseconds after a release that ends a click series and
            sets ``click_count``.  A press held longer than this is a hold, left out of the
            count.  0 turns click counting off.

    Attributes:
        pressed: True while the button is down, after debouncing.
        just_pressed: True only on the tick the press landed.
        just_released: True only on the tick the release landed.
        just_long_pressed: True only on the tick the hold reached ``long_press_ms``.
        just_repeated: True on each tick auto-repeat fires.
        just_clicked: True only on the tick a click series ended.
        held_ms: Milliseconds the button has been down.  After a release it keeps the length
            of that press, until the next press starts it again from 0.
        click_count: How many presses the click series that just ended held.  Read it when
            ``just_clicked`` is True.
        overflowed: True when edge capture dropped an edge since the last tick.  A signal
            that noisy needs hardware debouncing.
        on_press: Called with no arguments when the button goes down.
        on_release: Called with no arguments when the button comes up.
        on_long_press: Called with no arguments once per press, when the hold reaches
            ``long_press_ms``.
        on_repeat: Called with no arguments on each auto-repeat.
        on_click: Called with ``click_count`` when a click series ends.

    Raises:
        RuntimeError: ``pin`` was given on CPython, which has no pins to read, or on a
            CircuitPython build without the ``keypad`` module.
    """

    def __init__(
        self,
        pin: object | None = None,
        *,
        ticks: object,
        source: object | None = None,
        active_low: bool = True,
        settle_ms: int = DEFAULT_SETTLE_MS,
        long_press_ms: int = DEFAULT_LONG_PRESS_MS,
        repeat_ms: int = 0,
        repeat_delay_ms: int = DEFAULT_REPEAT_DELAY_MS,
        click_ms: int = 0,
    ) -> None:
        self._ticks = ticks

        if source is not None:
            self._source = source
        elif pin is not None:
            self._source = _select_source(
                (pin,), active_low=active_low, settle_ms=settle_ms, ticks=ticks,
            )
        else:
            self._source = None

        self._long_press_ms = long_press_ms
        self._repeat_ms = repeat_ms
        self._repeat_delay_ms = repeat_delay_ms
        self._click_ms = click_ms

        self.pressed = False
        self.just_pressed = False
        self.just_released = False
        self.just_long_pressed = False
        self.just_repeated = False
        self.just_clicked = False
        self.held_ms = 0
        self.click_count = 0
        self.overflowed = False

        self.on_press = None
        self.on_release = None
        self.on_long_press = None
        self.on_repeat = None
        self.on_click = None

        self._press_ms = 0
        self._long_fired = False
        self._repeat_next_ms = 0
        self._pending_clicks = 0
        self._click_deadline_ms = 0
        self._click_pending = False
        self._press_is_click = False

    def check(self, now_ms: int) -> bool:
        """Collect the edges captured since the last tick and update every reading.

        Call it once per pass of the loop.  It never waits.

        Args:
            now_ms: The current tick, from the clock passed as ``ticks``.

        Returns:
            True when anything happened this tick, which is when ``handle`` has callbacks to call.

        Raises:
            RuntimeError: The button was built with neither ``pin`` nor ``source``, as each
                key inside a ``Buttons`` is.  Check the ``Buttons`` instead.
        """
        source = self._source
        if source is None:
            raise RuntimeError(
                "this Button belongs to a Buttons and is driven by it; "
                "tick the Buttons instead of the key.",
            )
        source.poll(now_ms)
        self._begin_tick()
        while source.next_event():
            # A lone Button owns key 0.  Multi-key sources are the Buttons panel's job, so
            # anything else on the wire is not this button's news.
            if source.event_key == 0:
                self._apply_edge(source.event_pressed, source.event_ms)
        self.overflowed = source.overflowed
        source.overflowed = False
        return self._advance(now_ms)

    def handle(self, now_ms: int) -> None:
        """Call the ``on_`` callbacks for the events ``check`` reported this tick."""
        if self.just_pressed and self.on_press is not None:
            self.on_press()
        if self.just_released and self.on_release is not None:
            self.on_release()
        if self.just_long_pressed and self.on_long_press is not None:
            self.on_long_press()
        if self.just_repeated and self.on_repeat is not None:
            self.on_repeat()
        if self.just_clicked and self.on_click is not None:
            self.on_click(self.click_count)

    def next_deadline(self, now_ms: int) -> int | None:
        """Return the tick the next long press, repeat, or click window falls due, or None.

        ``Runner.wait`` reads it before sleeping, so those timed events fire on time.  A
        press needs no deadline: an edge that lands while the loop sleeps is captured with
        its own timestamp and reported on the next tick.
        """
        ticks = self._ticks
        nearest = None
        if self.pressed:
            if self._long_press_ms > 0 and not self._long_fired:
                nearest = ticks.ticks_add(self._press_ms, self._long_press_ms)
            if self._repeat_ms > 0:
                candidate = self._repeat_next_ms
                if nearest is None or ticks.ticks_diff(candidate, nearest) < 0:
                    nearest = candidate
            if self._click_ms > 0 and self._press_is_click:
                candidate = ticks.ticks_add(self._press_ms, self._click_ms)
                if nearest is None or ticks.ticks_diff(candidate, nearest) < 0:
                    nearest = candidate
        if self._click_pending:
            candidate = self._click_deadline_ms
            if nearest is None or ticks.ticks_diff(candidate, nearest) < 0:
                nearest = candidate
        return nearest

    def deinit(self) -> None:
        """Release the pin and stop the interrupt or ``keypad`` scan reading it.

        Call it before using the pin for something else.
        """
        if self._source is not None:
            self._source.deinit()

    def _begin_tick(self) -> None:
        """Clear the per-tick latches so this tick reports only its own news."""
        self.just_pressed = False
        self.just_released = False
        self.just_long_pressed = False
        self.just_repeated = False
        self.just_clicked = False

    def _apply_edge(self, pressed: bool, event_ms: int) -> None:
        """Fold one debounced edge into the key's state.

        ``event_ms`` is when the edge happened, which for a captured edge is earlier than the
        tick that noticed it.  Durations measure from there, so a slow loop reports the hold
        the user actually performed.
        """
        if pressed == self.pressed:
            return
        self.pressed = pressed
        if pressed:
            self._press_ms = event_ms
            self._long_fired = False
            self._repeat_next_ms = self._ticks.ticks_add(event_ms, self._repeat_delay_ms)
            self._click_pending = False
            self._press_is_click = True
            self.just_pressed = True
        else:
            held_ms = self._ticks.ticks_diff(event_ms, self._press_ms)
            self.held_ms = held_ms if held_ms > 0 else 0
            self.just_released = True
            if self._click_ms > 0 and self._press_is_click:
                self._pending_clicks += 1
                self._click_deadline_ms = self._ticks.ticks_add(event_ms, self._click_ms)
                self._click_pending = True

    def _advance(self, now_ms: int) -> bool:
        """Run the duration-driven events for this tick.

        Returns:
            True when this tick produced anything worth handling.
        """
        fired = self.just_pressed or self.just_released
        ticks = self._ticks
        if self.pressed:
            held_ms = ticks.ticks_diff(now_ms, self._press_ms)
            self.held_ms = held_ms if held_ms > 0 else 0
            if (
                self._long_press_ms > 0
                and not self._long_fired
                and self.held_ms >= self._long_press_ms
            ):
                self._long_fired = True
                self.just_long_pressed = True
                fired = True
            if self._repeat_ms > 0:
                behind_ms = ticks.ticks_diff(now_ms, self._repeat_next_ms)
                if behind_ms >= 0:
                    # Advance the next deadline from the deadline that earned this fire, not
                    # from the tick that noticed it, so a slow loop cannot stretch the
                    # cadence.  Whole periods missed during a stall are skipped over in one
                    # step, so catching up fires once rather than bursting.
                    periods_missed = behind_ms // self._repeat_ms + 1
                    self._repeat_next_ms = ticks.ticks_add(
                        self._repeat_next_ms, periods_missed * self._repeat_ms,
                    )
                    self.just_repeated = True
                    fired = True
            if (
                self._click_ms > 0
                and self._press_is_click
                and self.held_ms >= self._click_ms
            ):
                # This press has outlived the click window, so it is a hold rather than a
                # click.  Close whatever series was open instead of leaving it to be reopened
                # by the eventual release.
                self._press_is_click = False
                if self._pending_clicks > 0:
                    self.click_count = self._pending_clicks
                    self._pending_clicks = 0
                    self.just_clicked = True
                    fired = True
        if self._click_pending and ticks.ticks_diff(now_ms, self._click_deadline_ms) >= 0:
            self._click_pending = False
            self.click_count = self._pending_clicks
            self._pending_clicks = 0
            self.just_clicked = True
            fired = True
        return fired


class Buttons:
    """Several buttons read on one scan, each one a ``Button`` with its own readings and callbacks.

    ``buttons[0]`` is the ``Button`` for the first pin, and ``len(buttons)`` is the number of
    keys.  Call ``check(now_ms)`` on the ``Buttons``, which checks every key, and read each
    key's attributes.  The ``Buttons`` has its own ``on_press`` and ``on_release``, which
    take the key number, for one handler covering every key.  On CircuitPython one firmware
    ``keypad`` scan reads every pin, which costs less than a scan per key and lands two keys
    pressed together on the same tick.

    Args:
        pins: The pins the buttons are wired to, one per key, in the order to number them.
        ticks: The clock every duration is measured on, shared by the scan and every key, as
            for ``Button``.
        source: A ready-made edge source, used in place of ``pins``.  Tests pass
            ``FakeButtonSource`` from ``chumicro_buttons.testing``.
        active_low: True when a pressed button reads low, as for ``Button``.
        settle_ms: Debounce window in milliseconds, as for ``Button``.
        long_press_ms: Hold time in milliseconds before a key's ``just_long_pressed`` fires.
            0 turns long press off.
        repeat_ms: Milliseconds between a held key's ``just_repeated`` fires.  0 turns
            auto-repeat off.
        repeat_delay_ms: Hold time in milliseconds before auto-repeat starts.
        click_ms: Quiet time in milliseconds that ends a key's click series.  0 turns click
            counting off.

    Attributes:
        keys: The ``Button`` for each key, in pin order.
        overflowed: True when edge capture dropped an edge since the last tick.
        on_press: Called with the key number when any key goes down.
        on_release: Called with the key number when any key comes up.

    Raises:
        ValueError: ``pins`` is empty, or neither ``pins`` nor ``source`` was given.
        RuntimeError: ``pins`` was given on CPython, which has no pins to read, or on a
            CircuitPython build without the ``keypad`` module.
    """

    def __init__(
        self,
        pins: object | None = None,
        *,
        ticks: object,
        source: object | None = None,
        active_low: bool = True,
        settle_ms: int = DEFAULT_SETTLE_MS,
        long_press_ms: int = DEFAULT_LONG_PRESS_MS,
        repeat_ms: int = 0,
        repeat_delay_ms: int = DEFAULT_REPEAT_DELAY_MS,
        click_ms: int = 0,
    ) -> None:
        self._ticks = ticks
        if source is not None:
            self._source = source
        elif pins is not None:
            if len(pins) == 0:
                # An empty sequence usually means the pin list came from config that resolved
                # to nothing.  Building a zero-key panel would read as a program that simply
                # never sees a press.
                raise ValueError("Buttons was given an empty pins sequence")
            self._source = _select_source(
                pins, active_low=active_low, settle_ms=settle_ms, ticks=ticks,
            )
        else:
            raise ValueError("Buttons needs either pins= or source=")

        self.keys = []
        key_index = 0
        while key_index < self._source.key_count:
            self.keys.append(
                Button(
                    long_press_ms=long_press_ms,
                    repeat_ms=repeat_ms,
                    repeat_delay_ms=repeat_delay_ms,
                    click_ms=click_ms,
                    ticks=ticks,
                ),
            )
            key_index += 1

        self.overflowed = False
        self.on_press = None
        self.on_release = None

    def check(self, now_ms: int) -> bool:
        """Collect the edges captured since the last tick and update every key's readings.

        Call it once per pass of the loop.  It never waits.

        Args:
            now_ms: The current tick, from the clock passed as ``ticks``.

        Returns:
            True when any key had an event this tick, which is when ``handle`` has callbacks
                to call.
        """
        source = self._source
        source.poll(now_ms)
        keys = self.keys
        key_count = len(keys)
        index = 0
        while index < key_count:
            keys[index]._begin_tick()
            index += 1
        while source.next_event():
            keys[source.event_key]._apply_edge(source.event_pressed, source.event_ms)
        self.overflowed = source.overflowed
        source.overflowed = False
        fired = False
        index = 0
        while index < key_count:
            if keys[index]._advance(now_ms):
                fired = True
            index += 1
        return fired

    def handle(self, now_ms: int) -> None:
        """For each key in order, call its own callbacks, then this object's ``on_press`` or ``on_release``.

        The ``Buttons`` callbacks receive the key number.
        """
        keys = self.keys
        key_count = len(keys)
        index = 0
        while index < key_count:
            key = keys[index]
            key.handle(now_ms)
            if key.just_pressed and self.on_press is not None:
                self.on_press(index)
            if key.just_released and self.on_release is not None:
                self.on_release(index)
            index += 1

    def next_deadline(self, now_ms: int) -> int | None:
        """Return the tick any key's next long press, repeat, or click window falls due, or None."""
        ticks = self._ticks
        keys = self.keys
        key_count = len(keys)
        nearest = None
        index = 0
        while index < key_count:
            candidate = keys[index].next_deadline(now_ms)
            if candidate is not None and (
                nearest is None or ticks.ticks_diff(candidate, nearest) < 0
            ):
                nearest = candidate
            index += 1
        return nearest

    def deinit(self) -> None:
        """Release the pins and stop the interrupts or ``keypad`` scan reading them.

        Call it before using the pins for something else.
        """
        self._source.deinit()

    def __len__(self) -> int:
        """Return the number of keys."""
        return len(self.keys)

    def __getitem__(self, key_index: int) -> Button:
        """Return the ``Button`` for key number ``key_index``, counted from 0."""
        return self.keys[key_index]
