"""``EncoderSource`` and ``AnalogSource``: the contracts every per-runtime reader implements."""

#: How much of each new conversion a smoothed reading takes, as a right shift: the reading
#: keeps all but ``1 / 2 ** SMOOTHING_SHIFT`` of itself and takes the rest from the sample.
#: It runs after the median below and carries the whole burden of continuous noise, because a
#: median does nothing for that; the two reject different things and neither substitutes.
#:
#: A converter's noise is jumpy rather than merely wide, and it is the jumpiness that defeats
#: the deadband above it.  That deadband anchors on whichever sample tripped it, so a reading
#: that leaps between noise extremes drags the anchor across a step boundary and back.  This
#: removes the leaping, which is what lets the deadband behave the way it reads.  Four is the
#: shift the bench settled on: measured live against a potentiometer at the noisiest end of its
#: travel, twenty seconds of an untouched knob reported around 12000 movements unsmoothed, 949
#: at a shift of 2, and one at 4.
SMOOTHING_SHIFT = 4

def middle_of_three(first: int, second: int, third: int) -> int:
    """Return the middle of three readings, by comparison rather than by sorting.

    Three is the smallest window with a middle, and one wild sample can never be the middle
    of three, so a lone bad conversion is discarded outright rather than averaged in.  That
    is the half smoothing cannot do: fed one full-scale sample, a smoothed reading moved
    almost three steps and took 39 conversions to come back, while this moved nothing.  It
    costs no extra conversion, because the window holds readings the loop already took.

    What it does not do is quieten continuous noise, where it is nearly useless alone, so it
    runs ahead of the smoothing rather than instead of it.
    """
    if first > second:
        first, second = second, first
    if second > third:
        second = third
    if first > second:
        second = first
    return second


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
