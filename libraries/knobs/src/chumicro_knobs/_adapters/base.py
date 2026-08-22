"""``EncoderSource`` and ``AnalogSource``: the contracts every per-runtime reader implements."""

#: How much of each new conversion a smoothed reading takes, as a right shift: the reading
#: keeps all but ``1 / 2 ** SMOOTHING_SHIFT`` of itself and takes the rest from the sample.
#:
#: A converter's noise is jumpy rather than merely wide, and it is the jumpiness that defeats
#: the deadband above it.  That deadband anchors on whichever sample tripped it, so a reading
#: that leaps between noise extremes drags the anchor with it, and once a leap is wider than
#: one step the reported value flips every time.  Smoothing removes the leaping, which is what
#: lets the deadband behave the way it reads.
#:
#: It costs one add and one shift per tick and takes no extra conversion, because the loop
#: already samples far faster than a hand can move a knob.  Measured live against a
#: potentiometer at the top of its travel, where this converter is noisiest, four seconds of
#: an untouched knob reported 16116 movements unsmoothed, 593 at a shift of 2, 25 at 3, and
#: none from 4 upward.  Four is the first that settles it, so it is the one used.
#:
#: The window is counted in ticks rather than milliseconds, so a loop that runs flat out
#: settles inside a couple of milliseconds while a deliberately slow one takes longer.  Raise
#: it for a noisier converter and lower it for a loop that ticks rarely and wants the knob to
#: keep up.
SMOOTHING_SHIFT = 4


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
