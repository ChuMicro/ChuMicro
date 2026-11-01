"""``AnalogKnob``: a potentiometer or slider read as a step number that holds still.

Attributes:
    RAW_RANGE: 65536, one more than the largest raw reading.  A raw reading divided by it is
        the fraction of the sweep the knob has turned through.
    DEFAULT_STEPS: The default number of positions in a full sweep, 100, numbered 0 to 99.
    DEFAULT_DEADBAND: The default deadband, 512 raw counts.  A parked wiper still wanders a
        few counts, more on a noisy part or a long lead.  512 clears that and stays under
        one step at 100 steps, where a step spans 655 counts.
"""

import sys

RAW_RANGE = 65536
DEFAULT_STEPS = 100
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
    """One potentiometer or slider, read as a step number that holds still.

    Call ``check(now_ms)`` once per pass of the loop and read ``value``.  Or set
    ``on_change`` and register the knob with ``runner.add(knob, period_ms=20)``, and the
    runner calls ``handle``, which calls it.  ``check`` samples the pin, ignores any move of
    ``deadband`` counts or less, and scales the reading to a step from 0 to ``steps - 1``, so
    a volume control set to 47 reads 47 until it is turned.

    Args:
        pin: An analog-capable pin, such as ``board.A0`` on CircuitPython, or a pin number
            or ``machine.Pin`` on MicroPython.
        source: A ready-made converter, used in place of ``pin``.  Tests pass
            ``FakeAnalogSource`` from ``chumicro_knobs.testing``.
        steps: How many positions a full sweep reports.  ``value`` runs from 0 to
            ``steps - 1``.
        deadband: How many raw counts, on the 0 to 65535 scale, a reading must move beyond
            before ``value`` follows it.  Keep it under one step, ``65536 // steps`` counts,
            or the steps at the ends of the sweep become unreachable.

    Attributes:
        value: The step the knob points at, 0 at one end of the sweep and ``steps - 1`` at
            the other.
        raw: The 0 to 65535 reading ``value`` was worked out from.  It moves only when a
            reading clears the deadband, so it holds the settled reading.
        delta: Steps this tick added to ``value``, negative for the other direction.
        just_moved: True only on the tick ``value`` changed.
        on_change: Called with the new ``value`` when the knob moves.

    Raises:
        ValueError: Neither ``pin`` nor ``source`` was given.
        RuntimeError: ``pin`` was given on CPython, which has no converter to sample.
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

        self.value = 0
        self.raw = 0
        self.delta = 0
        self.just_moved = False
        self.on_change = None

    def check(self, now_ms: int) -> bool:
        """Sample the pin, and move ``value`` when the reading has moved past the deadband.

        Call it once per pass of the loop.  It never waits.

        Args:
            now_ms: The current tick, from ``ticks_ms()``.

        Returns:
            True when ``value`` changed, which is when ``handle`` has ``on_change`` to call.
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
        """Call ``on_change(value)`` when ``check`` reported a change this tick."""
        if self.just_moved and self.on_change is not None:
            self.on_change(self.value)

    def deinit(self) -> None:
        """Release the pin on CircuitPython, so it can be used for something else.

        MicroPython's converter holds no claim on the pin, so there it does nothing.
        """
        self._source.deinit()
