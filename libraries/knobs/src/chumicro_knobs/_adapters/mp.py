"""MicroPython sources: a capture interrupt for the shaft, ``machine.ADC`` for the wiper."""

__chumicro_runtimes__ = ("micropython",)  # pragma: no cover - MP runtime path

import array  # pragma: no cover - MP runtime path

import machine  # pragma: no cover - MP runtime path

from chumicro_knobs._adapters.base import SMOOTHING_SHIFT, middle_of_three

try:  # pragma: no cover - MP runtime path
    from micropython import const
except ImportError:
    def const(value):
        return value

# Quadrature decode, indexed by (previous_state << 2) | current_state where a state is
# (pin_a << 1) | pin_b.  Each byte holds the step plus one: 0 steps back, 1 stays put, 2 steps
# forward.  The four entries where both pins changed at once read as no movement, because a
# turning shaft cannot produce that and treating it as a step is how a dirty encoder invents
# detents.  ``bytes`` keeps the table in flash, so indexing it costs nothing on the heap.
_QUADRATURE_STEPS = (  # pragma: no cover - MP runtime path
    b"\x01\x00\x02\x01\x02\x01\x01\x00"
    b"\x00\x01\x01\x02\x01\x02\x00\x01"
)

# Slots the interrupt writes in the counter array: detents counted so far, quadrature steps
# banked toward the detent in progress, and the pin state the last edge saw.
_POSITION = const(0)  # pragma: no cover - MP runtime path
_SUB_COUNT = const(1)  # pragma: no cover - MP runtime path
_PREVIOUS_STATE = const(2)  # pragma: no cover - MP runtime path


class MpEncoderSource:  # pragma: no cover - MP runtime path
    """Quadrature counting done by a pin interrupt this class installs and owns.

    MicroPython has no encoder peripheral binding, so both pins get an interrupt into one
    handler, which is what catches a spin starting and ending between two passes of the
    loop.  ``pin_a`` and ``pin_b`` take a pin number or a ``machine.Pin``, and
    ``detent_steps`` is the quadrature steps that make one detent.
    """

    def __init__(self, pin_a, pin_b, *, detent_steps: int) -> None:
        self._pin_a = machine.Pin(pin_a, machine.Pin.IN, machine.Pin.PULL_UP)
        self._pin_b = machine.Pin(pin_b, machine.Pin.IN, machine.Pin.PULL_UP)
        self._detent_steps = detent_steps

        # Sized once here so the interrupt only ever writes into slots that already exist.
        self._counters = array.array("l", (0, 0, 0))
        self._counters[_PREVIOUS_STATE] = (self._pin_a.value() << 1) | self._pin_b.value()

        # Bound once and kept, so no callable is built on the way into an interrupt.
        self._edge_handler = self._on_edge
        edges = machine.Pin.IRQ_RISING | machine.Pin.IRQ_FALLING
        self._pin_a.irq(handler=self._edge_handler, trigger=edges)
        self._pin_b.irq(handler=self._edge_handler, trigger=edges)

        self.raw_position = 0

    def _on_edge(self, pin) -> None:
        """Fold one pin change into the detent count.  This runs in interrupt context.

        It reads two pins, indexes a table that lives in flash, and writes small integers
        into an array that already exists, so nothing here reaches the heap.  It decides
        nothing either: bounds, wrap, and every callback happen later on the shared tick, in
        normal context, where a slow or careless callback is harmless.  ``pin`` goes unread,
        because both pins share this handler and both are sampled here anyway.
        """
        counters = self._counters
        detent_steps = self._detent_steps
        state = (self._pin_a.value() << 1) | self._pin_b.value()
        step = _QUADRATURE_STEPS[(counters[_PREVIOUS_STATE] << 2) | state] - 1
        counters[_PREVIOUS_STATE] = state
        sub_count = counters[_SUB_COUNT] + step
        if sub_count >= detent_steps:
            counters[_POSITION] += 1
            sub_count = 0
        elif sub_count <= -detent_steps:
            counters[_POSITION] -= 1
            sub_count = 0
        counters[_SUB_COUNT] = sub_count

    def poll(self, now_ms: int) -> None:
        """Copy over the count the interrupt kept while the loop was somewhere else."""
        self.raw_position = self._counters[_POSITION]

    def deinit(self) -> None:
        """Take the interrupt off both pins so nothing counts after this."""
        self._pin_a.irq(handler=None)
        self._pin_b.irq(handler=None)


class MpAnalogSource:  # pragma: no cover - MP runtime path
    """One ``machine.ADC``, sampled on the tick that asks for it.

    ``pin`` is a pin number or a ``machine.Pin``.  ``read_u16`` reports 0 to 65535 on every
    port, stretched up from whatever the converter's native width is, so a 12-bit part
    takes the same step arithmetic as a wider one.
    """

    def __init__(self, pin) -> None:
        self._converter = machine.ADC(pin)
        reading = self._converter.read_u16()
        # The window starts full of the first reading so the median has three from the outset.
        self._recent = [reading, reading, reading]
        self._slot = 0
        # Carried scaled up by the shift so the fraction it keeps survives integer division.
        self._smoothed = reading << SMOOTHING_SHIFT
        self.raw = reading

    def poll(self, now_ms: int) -> None:
        """Convert once, drop it if it is a lone outlier, and smooth what is left."""
        recent = self._recent
        recent[self._slot] = self._converter.read_u16()
        slot = self._slot + 1
        self._slot = 0 if slot >= 3 else slot
        middle = middle_of_three(recent[0], recent[1], recent[2])
        self._smoothed += middle - (self._smoothed >> SMOOTHING_SHIFT)
        self.raw = self._smoothed >> SMOOTHING_SHIFT

    def deinit(self) -> None:
        """Do nothing, because ``machine.ADC`` claims no pin it could hand back.

        The method is here so a knob is torn down the same way on either runtime.
        """
