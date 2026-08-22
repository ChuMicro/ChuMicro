"""``EncoderSource`` and ``AnalogSource``: the contracts every per-runtime reader implements."""


class EncoderSource:
    """Contract for the reader that turns two quadrature pins into a detent count.

    A source owns capture and quadrature decode, including the division into the clicks a
    wrist feels.  Bounds, wrap, and the per-tick readings are decided above it.
    """

    # Plain class, not a Protocol: MicroPython has no typing module to import.

    #: Detents counted since the source was built, rising one way and falling the other.
    #: Nothing clamps or resets it, so the difference between two ticks is the turning.
    raw_position = 0

    def poll(self, now_ms: int) -> None:
        """Take one capture step against the tick ``now_ms``, if this source needs one."""
        raise NotImplementedError

    def deinit(self) -> None:
        """Release the pins and any interrupt this source installed."""
        raise NotImplementedError


class AnalogSource:
    """Contract for the reader that turns one analog pin into a number.

    A source owns the conversion and stops there.  The deadband and the quantization into
    steps are decided above it.
    """

    #: Most recent conversion, 0 at the bottom of the sweep and 65535 at the top, whatever
    #: the converter's native width is.
    raw = 0

    def poll(self, now_ms: int) -> None:
        """Convert once, as of the tick ``now_ms``, and store the answer in ``raw``."""
        raise NotImplementedError

    def deinit(self) -> None:
        """Release the pin this source claimed."""
        raise NotImplementedError
