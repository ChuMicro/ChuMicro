"""Buttons and switches: debounced level, edges, long press, repeat, and click counting."""

import sys

#: Quiet period a raw signal must hold before an edge is believed.  Zero trusts the signal
#: as-is, which is what a hardware-debounced button wants.  It is also the shortest press
#: that can be reported, so this default is a balance: a tactile switch settles inside a
#: millisecond, a big toggle can bounce for twenty, and a fast tap can be over in ten.
DEFAULT_SETTLE_MS = 10

#: How long a press must be held before ``just_long_pressed`` fires.  Zero disables it.
DEFAULT_LONG_PRESS_MS = 500

#: How long a press must be held before auto-repeat starts ticking.
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
    """One momentary button or switch, read as a debounced level plus what it meant.

    Every reading is a plain attribute refreshed by ``check(now_ms)``, and the ``just_`` family
    is true only for the tick the thing happened on, so a loop can read them without consuming
    anything.  A switch that stays where you put it uses the same object, reading ``pressed``
    and watching the edges for when it moved.  Constructing with ``pin`` builds the runtime's
    own source, a firmware ``keypad`` scan on CircuitPython and a capture interrupt on
    MicroPython, and both catch a tap that starts and ends between two passes of your loop.

    Args:
        pin: Runtime pin object for the key, or None when a parent drives this button.
        ticks: The clock every duration here is judged by, ``chumicro_timing.ticks`` or
            anything shaped like it.  Required, and it is the only clock this library reads,
            so the ticks you pass ``check(now_ms)`` and the settle window the source
            debounces against share one time base by construction.
        source: Pre-built edge source; overrides ``pin``.  Tests inject a fake here.
        active_low: True when a pressed key reads low.  True suits a button wired to ground
            with the internal pull-up enabled, which is nearly always the wiring.
        settle_ms: Debounce window in milliseconds, and the shortest press that can be
            reported.  Raise it for a switch that bounces badly, lower it for fast tapping,
            and use zero for a button with hardware debouncing behind it.
        long_press_ms: Hold time that fires ``just_long_pressed``.  Zero disables it.
        repeat_ms: Interval between ``just_repeated`` fires while held.  Zero disables it.
        repeat_delay_ms: Hold time before repeat starts.
        click_ms: Quiet time after a release that closes a click series and publishes
            ``click_count``.  Zero disables click counting.
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

        #: True while the key is down, after debouncing.
        self.pressed = False
        #: True only on the tick the press edge landed.
        self.just_pressed = False
        #: True only on the tick the release edge landed.
        self.just_released = False
        #: True only on the tick the hold passed ``long_press_ms``.
        self.just_long_pressed = False
        #: True on each tick auto-repeat fires.
        self.just_repeated = False
        #: True only on the tick a click series closed.
        self.just_clicked = False
        #: Milliseconds the key has been down.  After a release it holds how long that press
        #: lasted, so an ``on_release`` handler can read it, and it resets on the next press.
        self.held_ms = 0
        #: Presses in the click series that just closed; read it when ``just_clicked``.
        self.click_count = 0
        #: True when capture dropped an edge since the last tick.  A signal this noisy wants
        #: hardware debouncing.
        self.overflowed = False

        #: Called with no arguments when the key goes down.
        self.on_press = None
        #: Called with no arguments when the key comes up.
        self.on_release = None
        #: Called with no arguments once per press, after ``long_press_ms``.
        self.on_long_press = None
        #: Called with no arguments on each auto-repeat.
        self.on_repeat = None
        #: Called with the press count when a click series closes.
        self.on_click = None

        self._press_ms = 0
        self._long_fired = False
        self._repeat_next_ms = 0
        self._pending_clicks = 0
        self._click_deadline_ms = 0
        self._click_pending = False
        self._press_is_click = False

    def check(self, now_ms: int) -> bool:
        """Drain captured edges and advance the timers by one tick.

        Args:
            now_ms: Tick this pass of the loop is measured from.

        Returns:
            True when anything happened, so a quiet tick can skip ``handle``.
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
        """Call whichever callbacks this tick's readings earned."""
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

    def deinit(self) -> None:
        """Release the pins and any interrupt the source installed."""
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
    """Several keys on one source, ticked together and read one key at a time.

    ``buttons[0]`` is a :class:`Button` carrying that key's readings and its own callbacks, and
    the whole-panel callbacks take the key number instead.  On CircuitPython this is one
    firmware ``keypad`` scan across all the pins rather than one per key, which is both cheaper
    and what makes chords land on the same tick.

    Args:
        pins: Runtime pin objects, one per key.
        ticks: The clock every duration here is judged by, ``chumicro_timing.ticks`` or
            anything shaped like it.  Required, and it reaches the scan and every key below,
            so the whole panel measures against one time base.
        source: Pre-built edge source; overrides ``pins``.  Tests inject a fake here.
        active_low: True when a pressed key reads low.
        settle_ms: Debounce window in milliseconds; 0 trusts the signal.
        long_press_ms: Hold time that fires ``just_long_pressed``.  Zero disables it.
        repeat_ms: Interval between repeat fires while held.  Zero disables it.
        repeat_delay_ms: Hold time before repeat starts.
        click_ms: Quiet time that closes a click series.  Zero disables click counting.
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

        #: One :class:`Button` per key, in the order the pins were given.
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

        #: True when capture dropped an edge since the last tick.
        self.overflowed = False
        #: Called with the key number when any key goes down.
        self.on_press = None
        #: Called with the key number when any key comes up.
        self.on_release = None

    def check(self, now_ms: int) -> bool:
        """Drain captured edges into every key and advance their timers.

        Args:
            now_ms: Tick this pass of the loop is measured from.

        Returns:
            True when any key produced news this tick, so a quiet tick can skip ``handle``.
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
        """Call the per-key callbacks, then the whole-panel ones."""
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

    def deinit(self) -> None:
        """Release the pins and any interrupt the source installed."""
        self._source.deinit()

    def __len__(self) -> int:
        """Return how many keys this panel reads."""
        return len(self.keys)

    def __getitem__(self, key_index: int) -> Button:
        """Return the :class:`Button` for ``key_index``."""
        return self.keys[key_index]
