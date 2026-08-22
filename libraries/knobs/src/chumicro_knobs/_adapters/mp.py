"""MicroPython sources: a capture interrupt for the shaft, ``machine.ADC`` for the wiper."""

__chumicro_runtimes__ = ("micropython",)  # pragma: no cover - MP runtime path

import array  # pragma: no cover - MP runtime path

import machine  # pragma: no cover - MP runtime path

#: Quadrature decode, indexed by ``(previous_state << 2) | current_state`` where a state
#: is ``(pin_a << 1) | pin_b``.  Each byte holds the step plus one, so 0 means a step
#: back, 1 means no movement, and 2 means a step forward.  Four of the entries cover a
#: state where both pins changed at once, which a turning shaft cannot produce: either a
#: contact bounced or an edge went by unseen.  Reading them as no movement is what stops
#: a dirty encoder from inventing detents.  Keeping the table in ``bytes`` puts it in
#: flash and makes indexing it cost nothing on the heap.
#:
#: The sixteen entries match CircuitPython's own ``transitions[16]`` in
#: ``shared-module/rotaryio/IncrementalEncoder.c`` one for one, which is deliberate:
#: a shaft turned the same way must report the same sign on both runtimes.
_QUADRATURE_STEPS = (  # pragma: no cover - MP runtime path
    b"\x01\x00\x02\x01\x02\x01\x01\x00"
    b"\x00\x01\x01\x02\x01\x02\x00\x01"
)

#: Slot in the counter array holding detents counted so far.
_POSITION = 0  # pragma: no cover - MP runtime path

#: Slot holding quadrature steps banked toward the detent in progress.
_SUB_COUNT = 1  # pragma: no cover - MP runtime path

#: Slot holding the pin state the last interrupt saw.
_PREVIOUS_STATE = 2  # pragma: no cover - MP runtime path


class MpEncoderSource:  # pragma: no cover - MP runtime path
    """Quadrature counting done by an interrupt this class owns and hides.

    MicroPython has no encoder peripheral binding, so the only way to catch a spin that
    starts and ends between two passes of the loop is a pin interrupt.  Both pins get
    one, both fire into the same handler, and the handler is installed with ``hard=True``
    so it runs at once rather than waiting for the interpreter to reach a safe point.

    The handler obeys four conditions, and they are the reason it is safe to install:
    it allocates nothing, it records raw movement instead of deciding what the movement
    means, it runs no code the application wrote, and it can lose nothing because the
    detent count it folds each step into has no queue to fill up.

    Args:
        pin_a: First quadrature pin, as a pin number or a ``machine.Pin``.
        pin_b: Second quadrature pin.
        detent_steps: Quadrature steps that make one detent.
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
        self._pin_a.irq(handler=self._edge_handler, trigger=edges, hard=True)
        self._pin_b.irq(handler=self._edge_handler, trigger=edges, hard=True)

        self.raw_position = 0

    def _on_edge(self, pin) -> None:
        """Fold one pin change into the detent count.  This runs in interrupt context.

        It reads two pins, indexes a table that lives in flash, and writes small integers
        into an array that already exists, so nothing here reaches the heap.  It decides
        nothing either: bounds, wrap, and every callback happen later, on the shared tick,
        in normal context, where a slow or careless callback is harmless.

        Args:
            pin: The pin that changed.  Both pins share this handler and both are read
                here, so which of them fired makes no difference.
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
        """Copy over the count the interrupt kept while the loop was somewhere else.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        self.raw_position = self._counters[_POSITION]

    def deinit(self) -> None:
        """Take the interrupt off both pins so nothing counts after this."""
        self._pin_a.irq(handler=None)
        self._pin_b.irq(handler=None)


class MpAnalogSource:  # pragma: no cover - MP runtime path
    """One ``machine.ADC``, sampled on the tick that asks for it.

    ``read_u16`` reports on a 0 to 65535 scale on every port, stretched up from whatever
    the converter's native width is, so a 12-bit part reads on the same scale as a wider
    one and the same step arithmetic works everywhere.

    Args:
        pin: Analog-capable pin, as a pin number or a ``machine.Pin``.
    """

    def __init__(self, pin) -> None:
        self._converter = machine.ADC(pin)
        self.raw = self._converter.read_u16()

    def poll(self, now_ms: int) -> None:
        """Convert once and keep the answer.

        Args:
            now_ms: Shared tick timestamp for this pass of the loop.
        """
        self.raw = self._converter.read_u16()

    def deinit(self) -> None:
        """Do nothing, because ``machine.ADC`` claims no pin it could hand back.

        The class carries this method so a knob can be torn down the same way whatever
        runtime it is on, rather than making the caller ask which one it is running.
        """
