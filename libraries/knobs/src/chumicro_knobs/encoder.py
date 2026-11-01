"""``Encoder``: a rotary encoder read as a position counted in detents, with optional bounds and wrap.

Attributes:
    DEFAULT_DETENT_STEPS: The default number of quadrature steps in one detent, 4.  A
        detent is the click felt as the shaft turns.
"""

import sys

DEFAULT_DETENT_STEPS = 4


def _select_encoder_source(pin_a, pin_b, *, detent_steps):
    """Return the quadrature source this runtime can build for two pins."""
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
    """One rotary encoder, read as a position counted in detents.

    Call ``check(now_ms)`` once per pass of the loop and read ``position`` and ``delta``.  Or
    set ``on_change`` and register the encoder with ``runner.add(encoder, period_ms=20)``,
    and the runner calls ``handle``, which calls it.  An encoder senses how far its shaft
    turns and never where it points, so ``position`` counts detents from where the shaft sat
    at startup.  The push switch under the shaft is a separate part on its own pin.

    Args:
        pin_a: The first quadrature pin, such as ``board.GP16`` on CircuitPython, or a pin
            number or ``machine.Pin`` on MicroPython.
        pin_b: The second quadrature pin.  Swapping the two reverses which way counts up.
        source: A ready-made quadrature source, used in place of the pins.  Tests pass
            ``FakeEncoderSource`` from ``chumicro_knobs.testing``.
        detent_steps: Quadrature steps in one detent.  4 suits a panel-mount encoder that
            clicks once per cycle.  1 suits a smooth encoder with no clicks.
        bounds: An inclusive ``(low, high)`` range that holds ``position``, or None to let it
            run in both directions without limit.
        wrap: True carries ``position`` around from one end of ``bounds`` to the other, as a
            menu ring or a hue picker wants.  False stops it at the ends.  Needs ``bounds``.

    Attributes:
        position: Detents turned so far, starting at 0, or at the nearer end of ``bounds``
            when 0 lies outside them.  Assign to it to restore a saved reading.
        delta: Detents this tick added to ``position``, negative for the other direction.
            Turning past an end of ``bounds`` without ``wrap`` adds 0.
        just_moved: True only on the tick ``position`` changed.
        on_change: Called with ``delta`` when the knob turns.

    Raises:
        ValueError: ``detent_steps`` is below 1, neither both pins nor ``source`` was
            given, or ``wrap`` is True without ``bounds``.
        RuntimeError: Pins were given on CPython, which has no pins to watch.
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
        if detent_steps < 1:
            # At zero the detent guard is satisfied by a step of zero, so a shaft
            # standing still counts up; below zero every edge counts.
            raise ValueError("detent_steps must be 1 or more")
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

        self.position = start_position
        self.delta = 0
        self.just_moved = False
        self.on_change = None

        self._last_raw_position = self._source.raw_position

    def check(self, now_ms: int) -> bool:
        """Read how far the shaft turned since the last tick and add it to ``position``.

        Call it once per pass of the loop.  It never waits.

        Args:
            now_ms: The current tick, from ``ticks_ms()``.

        Returns:
            True when ``position`` changed, which is when ``handle`` has ``on_change`` to call.
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
        """Call ``on_change(delta)`` when ``check`` reported a change this tick."""
        if self.just_moved and self.on_change is not None:
            self.on_change(self.delta)

    def deinit(self) -> None:
        """Release the pins and stop the interrupt or firmware counter reading them.

        Call it before using the pins for something else.
        """
        self._source.deinit()
