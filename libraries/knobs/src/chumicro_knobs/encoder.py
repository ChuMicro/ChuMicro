"""Rotary encoders: detents counted into a position, with optional bounds and wrap."""

import sys

#: Quadrature steps that make one detent, the click a wrist feels as the shaft turns.
#: Four matches CircuitPython's ``rotaryio.IncrementalEncoder``, whose ``divisor``
#: argument defaults to 4 and whose documentation names 1 for an encoder with no
#: detents and 2 for one with two detents per quadrature cycle.
DEFAULT_DETENT_STEPS = 4


def _select_encoder_source(pin_a, pin_b, *, detent_steps):
    """Return the quadrature source this runtime can build for two pins.

    Imported per runtime so a board only parses the adapter it actually uses.

    Args:
        pin_a: First quadrature pin, named the way this runtime names pins.
        pin_b: Second quadrature pin.
        detent_steps: Quadrature steps the source counts as one detent.

    Returns:
        A source honouring the ``EncoderSource`` contract.
    """
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_knobs._adapters.cp import CpEncoderSource
        return CpEncoderSource(pin_a, pin_b, detent_steps=detent_steps)
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_knobs._adapters.mp import MpEncoderSource
        return MpEncoderSource(pin_a, pin_b, detent_steps=detent_steps)
    raise RuntimeError(
        "CPython has no pins to watch a shaft with.  Build the encoder with "
        "source=FakeEncoderSource() from chumicro_knobs.testing and turn it from "
        "your test, or run this on CircuitPython or MicroPython.",
    )


class Encoder:
    """One rotary encoder, read as a position in detents plus how far it just turned.

    Every reading is a plain attribute refreshed by ``check(now_ms)``.  ``just_moved``
    is true only for the tick the turning landed on, so a loop can read it without
    consuming anything:

        while True:
            now = ticks_ms()
            encoder.check(now)
            if encoder.just_moved:
                volume += encoder.delta

    ``position`` starts at zero and counts detents from there, so it is a running total
    rather than an angle: an encoder knows how far its shaft moved and never where the
    shaft is pointing.  Give ``bounds`` to hold the total inside a range, and ``wrap``
    to carry it around the ends of that range instead of stopping at them, which is
    what a hue selector or a menu ring wants.

    The push switch under the shaft is a separate part.  Read it with a button object
    on its own pin; this class watches the two quadrature pins and nothing else.

    Args:
        pin_a: First quadrature pin, named the way this runtime names pins.  Pass both
            pins or pass ``source``.
        pin_b: Second quadrature pin.  Swapping the two reverses which way counts up.
        source: Pre-built quadrature source; overrides the pins.  Tests inject a fake
            here.
        detent_steps: Quadrature steps that make one detent.  Four suits an encoder
            with a click at every cycle, which is nearly all of the panel-mount ones.
            Use 1 for a smooth encoder with no clicks at all.
        bounds: ``(low, high)`` inclusive range that ``position`` is held inside, or
            None to let it run in both directions forever.
        wrap: True to carry ``position`` from one end of ``bounds`` to the other rather
            than stopping there.  Needs ``bounds``.
    """

    def __init__(
        self,
        pin_a: object | None = None,
        pin_b: object | None = None,
        *,
        source: object | None = None,
        detent_steps: int = DEFAULT_DETENT_STEPS,
        bounds: tuple[int, int] | None = None,
        wrap: bool = False,
    ) -> None:
        if source is not None:
            self._source = source
        elif pin_a is not None and pin_b is not None:
            self._source = _select_encoder_source(
                pin_a, pin_b, detent_steps=detent_steps,
            )
        else:
            raise ValueError("Encoder needs both pin_a= and pin_b=, or source=")

        if bounds is None:
            if wrap:
                raise ValueError("wrap=True needs bounds=(low, high) to wrap around")
            self._bounded = False
            self._low = 0
            self._high = 0
            self._span = 0
        else:
            self._bounded = True
            self._low = bounds[0]
            self._high = bounds[1]
            self._span = self._high - self._low + 1
        self._wrap = wrap

        start_position = 0
        if self._bounded:
            if start_position < self._low:
                start_position = self._low
            elif start_position > self._high:
                start_position = self._high

        #: Detents counted so far, held inside ``bounds`` when there are any.  Assign to
        #: it to set the reading without turning the shaft, which is how a value saved
        #: at shutdown is put back.
        self.position = start_position
        #: Detents this tick added to ``position``, negative the other way round.  Held
        #: against a bound with no wrap, the turning that did not fit reports as zero.
        self.delta = 0
        #: True only on the tick ``position`` changed.
        self.just_moved = False

        #: Called with the signed detent change when the knob turns.
        self.on_change = None

        self._last_raw_position = self._source.raw_position

    def check(self, now_ms: int) -> bool:
        """Read how far the shaft turned since the last tick and fold it into ``position``.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.

        Returns:
            True when ``position`` changed, which is the runner's gate for ``handle``.
        """
        source = self._source
        source.poll(now_ms)
        raw_position = source.raw_position
        moved = raw_position - self._last_raw_position
        if moved == 0:
            self.delta = 0
            self.just_moved = False
            return False
        self._last_raw_position = raw_position

        previous_position = self.position
        position = previous_position + moved
        if not self._bounded:
            delta = moved
        elif self._wrap:
            position = self._low + (position - self._low) % self._span
            delta = moved
        else:
            if position < self._low:
                position = self._low
            elif position > self._high:
                position = self._high
            delta = position - previous_position

        self.position = position
        self.delta = delta
        self.just_moved = delta != 0
        return self.just_moved

    def handle(self, now_ms: int) -> None:
        """Call ``on_change`` when this tick's turning earned it.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        if self.just_moved and self.on_change is not None:
            self.on_change(self.delta)

    def deinit(self) -> None:
        """Release the pins and any interrupt the source installed."""
        self._source.deinit()
