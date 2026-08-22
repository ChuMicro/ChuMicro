"""CircuitPython sources: ``rotaryio`` for the shaft, ``analogio`` for the wiper."""

__chumicro_runtimes__ = ("circuitpython",)  # pragma: no cover - CP runtime path

import analogio  # pragma: no cover - CP runtime path
import rotaryio  # pragma: no cover - CP runtime path


class CpEncoderSource:  # pragma: no cover - CP runtime path
    """Quadrature counting done by the firmware, in C, whatever Python is busy with.

    ``rotaryio.IncrementalEncoder`` watches the two pins from hardware rather than from
    the loop: an RP2040 build runs a state machine in the PIO block, and other builds
    use a pulse counter or a pin interrupt in the firmware's own C.  A fast spin during
    a flash write or a socket read is still counted, so a tick that arrives late reads
    the whole turn rather than the part of it that survived.

    ``divisor`` is where ``detent_steps`` lands, and the firmware handles the arithmetic
    of a turn that reverses part way into a detent.

    Args:
        pin_a: First quadrature pin.
        pin_b: Second quadrature pin.
        detent_steps: Quadrature steps that make one detent.
    """

    def __init__(self, pin_a, pin_b, *, detent_steps: int) -> None:
        self._encoder = rotaryio.IncrementalEncoder(pin_a, pin_b, divisor=detent_steps)
        self.raw_position = self._encoder.position

    def poll(self, now_ms: int) -> None:
        """Copy over the count the firmware kept while the loop was somewhere else.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        self.raw_position = self._encoder.position

    def deinit(self) -> None:
        """Release the two pins and the counter behind them."""
        self._encoder.deinit()


class CpAnalogSource:  # pragma: no cover - CP runtime path
    """One ``analogio.AnalogIn``, sampled on the tick that asks for it.

    ``AnalogIn.value`` is a 16-bit number on every board, scaled up by the firmware when
    the converter underneath is narrower, so a 12-bit part on an RP2040 and a 16-bit
    part elsewhere read on the same scale.

    Args:
        pin: Analog-capable pin.
    """

    def __init__(self, pin) -> None:
        self._converter = analogio.AnalogIn(pin)
        self.raw = self._converter.value

    def poll(self, now_ms: int) -> None:
        """Convert once and keep the answer.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        self.raw = self._converter.value

    def deinit(self) -> None:
        """Release the pin this knob claimed."""
        self._converter.deinit()
