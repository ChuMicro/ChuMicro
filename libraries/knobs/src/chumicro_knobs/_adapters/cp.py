"""CircuitPython sources: ``rotaryio`` for the shaft, ``analogio`` for the wiper."""

__chumicro_runtimes__ = ("circuitpython",)  # pragma: no cover - CP runtime path

import analogio  # pragma: no cover - CP runtime path
import rotaryio  # pragma: no cover - CP runtime path

from chumicro_knobs._adapters.base import SMOOTHING_SHIFT  # pragma: no cover - CP runtime path


class CpEncoderSource:  # pragma: no cover - CP runtime path
    """Quadrature counting done by ``rotaryio.IncrementalEncoder`` in firmware.

    The firmware watches the two pins from hardware rather than from the loop, so a fast
    spin during a flash write or a socket read is still counted and a late tick reads the
    whole turn.  ``detent_steps`` becomes the encoder's ``divisor``, which handles a turn
    that reverses part way into a detent.
    """

    def __init__(self, pin_a, pin_b, *, detent_steps: int) -> None:
        self._encoder = rotaryio.IncrementalEncoder(pin_a, pin_b, divisor=detent_steps)
        self.raw_position = self._encoder.position

    def poll(self, now_ms: int) -> None:
        """Copy over the count the firmware kept while the loop was somewhere else."""
        self.raw_position = self._encoder.position

    def deinit(self) -> None:
        """Release the two pins and the counter behind them."""
        self._encoder.deinit()


class CpAnalogSource:  # pragma: no cover - CP runtime path
    """One ``analogio.AnalogIn``, sampled on the tick that asks for it.

    ``AnalogIn.value`` reads 0 to 65535 on every board, scaled up by the firmware when the
    converter underneath is narrower.
    """

    def __init__(self, pin) -> None:
        self._converter = analogio.AnalogIn(pin)
        reading = self._converter.value
        # Carried scaled up by the shift so the fraction it keeps survives integer division.
        self._smoothed = reading << SMOOTHING_SHIFT
        self.raw = reading

    def poll(self, now_ms: int) -> None:
        """Convert once and fold the answer into the smoothed reading."""
        self._smoothed += self._converter.value - (self._smoothed >> SMOOTHING_SHIFT)
        self.raw = self._smoothed >> SMOOTHING_SHIFT

    def deinit(self) -> None:
        """Release the pin this knob claimed."""
        self._converter.deinit()
