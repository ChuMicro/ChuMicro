"""``EncoderSource`` and ``AnalogSource``: the contracts every per-runtime reader implements."""


class EncoderSource:
    """Duck-typed contract for the thing that turns two quadrature pins into a count.

    A source owns capture and quadrature decode, including the division that turns
    pin transitions into the clicks a wrist feels.  It never owns meaning: bounds,
    wrap, and the per-tick readings live in :class:`~chumicro_knobs.encoder.Encoder`
    so they behave identically on every runtime.

    Reading is allocation-free by design.  ``raw_position`` is a plain attribute
    rather than a method that returns one, so a tick costs a single attribute load
    and builds nothing.

    A concrete source implements ``poll(now_ms)`` and ``deinit()``, and keeps
    ``raw_position`` current.
    """

    # Plain class, not a Protocol: MicroPython has no typing module to import.

    #: Detents counted since the source was built, rising as the shaft turns one way
    #: and falling as it turns the other.  Nothing clamps or resets it, so the
    #: difference between two ticks is exactly the turning in between.
    raw_position = 0

    def poll(self, now_ms: int) -> None:
        """Take one capture step, if this source needs one.

        Sources backed by dedicated hardware or an interrupt count elsewhere and
        leave this empty.  Sources that sample read the pins here.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        raise NotImplementedError

    def deinit(self) -> None:
        """Release the pins and any interrupt this source installed."""
        raise NotImplementedError


class AnalogSource:
    """Duck-typed contract for the thing that turns one analog pin into a number.

    A source owns the conversion and stops there.  The deadband that keeps a noisy
    converter from dithering, and the quantization into steps, live in
    :class:`~chumicro_knobs.analog.AnalogKnob` so a reading means the same thing on
    every runtime.

    Every converter reports on the same 0 to 65535 scale here, whatever its native
    width is, so a 12-bit part and a 16-bit part are read by the same code.

    A concrete source implements ``poll(now_ms)`` and ``deinit()``, and keeps ``raw``
    current.
    """

    #: The most recent conversion, 0 at the bottom of the range and 65535 at the top.
    raw = 0

    def poll(self, now_ms: int) -> None:
        """Convert once and store the answer in ``raw``.

        There is no capture to miss here: an analog voltage is whatever it is at the
        instant it is sampled, so this reads the pin on the tick that asks.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        raise NotImplementedError

    def deinit(self) -> None:
        """Release the pin this source claimed."""
        raise NotImplementedError
