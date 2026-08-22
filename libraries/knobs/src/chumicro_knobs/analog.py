"""Analog knobs: a converter reading held still by a deadband and quantized into steps."""

import sys

#: Full scale of the raw reading plus one.  Dividing a 0 to 65535 conversion by this turns
#: it into a fraction of the sweep.
RAW_RANGE = 65536

#: How many positions a full sweep of the knob reports, numbered 0 to ``steps - 1``.
DEFAULT_STEPS = 100

#: How far the raw reading must move before ``value`` follows it.  A parked wiper still
#: wanders a few counts, more on a noisy part or a long lead; 512 clears that and stays
#: under one step at the default 100 steps, where a step spans 655 counts.
DEFAULT_DEADBAND = 512


def _select_analog_source(pin):
    """Return the converter this runtime can build for one pin."""
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_knobs._adapters.cp import CpAnalogSource
        return CpAnalogSource(pin)
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_knobs._adapters.mp import MpAnalogSource
        return MpAnalogSource(pin)
    raise RuntimeError(
        "CPython has no converter to sample.  Build the knob with "
        "source=FakeAnalogSource() from chumicro_knobs.testing and set a reading from "
        "your test, or run this on CircuitPython or MicroPython.",
    )


class AnalogKnob:
    """One potentiometer or slider, read as a step number that stops rattling.

    Every reading is a plain attribute refreshed by ``check(now_ms)``, and ``just_moved`` is
    true only for the tick the knob moved on.  ``deadband`` is the analog counterpart of a
    button's debounce, and ``steps`` gives the reading a size a person can aim at, so a
    volume control lands on 47 and stays there.  Sampling happens on the tick that asks for
    it, because a voltage has no edge to miss between two passes of the loop.

    Args:
        pin: Analog-capable pin, named the way this runtime names pins.  Pass a pin or pass
            ``source``.
        source: Pre-built converter; overrides ``pin``.  Tests inject a fake here.
        steps: How many positions the sweep reports.  ``value`` runs 0 to ``steps - 1``.
        deadband: How far the raw 0 to 65535 reading must move before ``value`` follows.
            Keep it under one step, ``65536 // steps`` counts, or the steps at the edges
            become unreachable.
    """

    def __init__(
        self,
        pin: object | None = None,
        *,
        source: object | None = None,
        steps: int = DEFAULT_STEPS,
        deadband: int = DEFAULT_DEADBAND,
    ) -> None:
        if source is not None:
            self._source = source
        elif pin is not None:
            self._source = _select_analog_source(pin)
        else:
            raise ValueError("AnalogKnob needs either pin= or source=")

        self._steps = steps
        self._deadband = deadband

        #: Where the knob points, 0 at one end of the sweep and ``steps - 1`` at the other.
        self.value = 0
        #: The 0 to 65535 reading ``value`` was worked out from.  It moves only when the
        #: knob clears the deadband, so it is the settled reading rather than the newest.
        self.raw = 0
        #: Steps this tick added to ``value``, negative the other way round.
        self.delta = 0
        #: True only on the tick ``value`` changed.
        self.just_moved = False
        #: Called with the new step number when the knob moves.
        self.on_change = None

    def check(self, now_ms: int) -> bool:
        """Sample the pin and let ``value`` follow it when the reading cleared the deadband.

        Args:
            now_ms: Tick this pass of the loop is measured from.

        Returns:
            True when ``value`` changed, so a quiet tick can skip ``handle``.
        """
        source = self._source
        source.poll(now_ms)
        raw = source.raw
        if abs(raw - self.raw) <= self._deadband:
            self.delta = 0
            self.just_moved = False
            return False

        self.raw = raw
        value = raw * self._steps // RAW_RANGE
        delta = value - self.value
        self.value = value
        self.delta = delta
        self.just_moved = delta != 0
        return self.just_moved

    def handle(self, now_ms: int) -> None:
        """Call ``on_change`` when this tick's movement earned it."""
        if self.just_moved and self.on_change is not None:
            self.on_change(self.value)

    def deinit(self) -> None:
        """Release the pin the source claimed."""
        self._source.deinit()
