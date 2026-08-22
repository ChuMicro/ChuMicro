"""The ``machine`` stub and the hand-driven shaft the MicroPython source tests run on.

``chumicro_knobs._adapters.mp`` does ``import machine`` at module top, which no host
interpreter has, so this module stands a stub in ``sys.modules`` for the length of that
import and hands the source's two classes on to the test file.  The stub's ``Pin`` and
``ADC`` hand back the fake the test already holds, rather than making one it could not
reach, which is what lets a test drive the pins the source installed its interrupt on.

This module is staged onto the device next to the importing test file by the pytest-device
staging path (underscore-prefixed sibling modules ride along as ``extra_modules``); on the
host and unix-port runs the test directory is on ``sys.path``, so ``from _mp_helpers import
...`` resolves there too.

Plain classes rather than ``types.ModuleType`` instances, because the MP and CP unix-ports
omit the ``types`` module.
"""

#: Host-only support module: stubs a runtime-specific firmware import so off-target
#: adapter source loads on host interpreters.  Carries no runtime marker — it ships
#: alongside the test file that imports it and never runs standalone.
__chumicro_test_support__ = True

import sys

from chumicro_test_harness.patching import FakeModule, SwapItem

#: The four pin states one turn of the shaft passes through, as ``(pin_a, pin_b)``, in the
#: order a forward turn produces them.  Neighbours differ in exactly one pin, which is what
#: makes the pair a quadrature signal and what lets the decode name a direction at all.
FORWARD_CYCLE = ((1, 1), (0, 1), (0, 0), (1, 0))

#: The four state changes a turning shaft cannot make, because both pins moved at once.
#: Noise and a dirty contact can still produce them, so the decode has to answer for them.
IMPOSSIBLE_JUMPS = (
    ((1, 1), (0, 0)),
    ((0, 0), (1, 1)),
    ((0, 1), (1, 0)),
    ((1, 0), (0, 1)),
)

#: The three counter slots the interrupt writes, mirroring ``_POSITION``, ``_SUB_COUNT`` and
#: ``_PREVIOUS_STATE`` in the module under test.  They are spelled out again here rather than
#: imported because ``const()`` under a leading-underscore name is a compile-time constant on
#: MicroPython and CircuitPython: the value folds into the bytecode and the module never binds
#: the name, so importing it works on a host and fails everywhere the library actually ships.
DETENTS = 0
BANKED_STEPS = 1
LAST_STATE = 2


class FakePin:
    """One ``machine.Pin`` a test drives by hand: it reports a level and holds an IRQ.

    ``level`` is what the pin reads and the shaft assigns it directly.  ``fire`` runs
    whatever handler was installed, which is how a test stands in for the interrupt a real
    edge would raise.  A pin with no handler on it fires nothing, which is what a detached
    interrupt looks like.
    """

    def __init__(self, level: int = 1) -> None:
        self.level = level
        self.mode = None
        self.pull = None
        self.handler = None
        self.trigger = 0
        self.hard = False

    def value(self) -> int:
        """Return what this pin currently reads."""
        return self.level

    def irq(self, handler=None, trigger=0, hard=False) -> None:
        """Install (or with ``handler=None`` remove) the edge handler and its terms."""
        self.handler = handler
        self.trigger = trigger
        self.hard = hard

    def fire(self) -> None:
        """Run the handler installed on this pin, the way an edge on it would."""
        if self.handler is not None:
            self.handler(self)


class PinType:
    """Stands in for ``machine.Pin``, both as the constructor and as the constants on it.

    The source builds its pins with ``machine.Pin(pin, mode, pull)``, so this hands back
    the ``FakePin`` the test already holds rather than making one the test could not reach.
    MicroPython's own ``Pin`` takes a ``Pin`` as its id the same way.
    """

    IN = 0
    PULL_UP = 2
    IRQ_RISING = 4
    IRQ_FALLING = 8

    def __call__(self, pin, mode=None, pull=None):
        """Record the direction and pull that were asked for, and hand the pin back."""
        pin.mode = mode
        pin.pull = pull
        return pin


class FakeConverter:
    """One ``machine.ADC`` a test drives by hand: it reports whatever ``reading`` holds."""

    def __init__(self, reading: int = 0) -> None:
        self.reading = reading
        self.conversions = 0

    def read_u16(self) -> int:
        """Return the parked reading, and count that a conversion was asked for."""
        self.conversions += 1
        return self.reading


class ConverterType:
    """Stands in for ``machine.ADC``, handing back the fake converter it was called with."""

    def __call__(self, pin):
        """Return the pin, which here is the fake converter the test is holding."""
        return pin


_MACHINE = FakeModule()
_MACHINE.Pin = PinType()
_MACHINE.ADC = ConverterType()

# The source reaches for ``machine`` at import, not at construction, so the stub has to be
# standing before the module loads.  It keeps the stub in its own globals afterwards, which
# is why sys.modules can go back to normal on the way out of this block.
with SwapItem(sys.modules, "machine", _MACHINE):
    from chumicro_knobs._adapters.mp import _QUADRATURE_STEPS as QUADRATURE_STEPS
    from chumicro_knobs._adapters.mp import MpAnalogSource, MpEncoderSource, const

#: What the test file imports from here.  Three of these are the module under test's own
#: names, passed straight through, so the stub above stays the only place that has to be
#: standing before that import happens.
__all__ = (
    "BANKED_STEPS",
    "DETENTS",
    "FORWARD_CYCLE",
    "IMPOSSIBLE_JUMPS",
    "LAST_STATE",
    "QUADRATURE_STEPS",
    "FakeConverter",
    "MpAnalogSource",
    "PinType",
    "Shaft",
    "const",
)


class Shaft:
    """Two fake pins and the source watching them, turned one quadrature step at a time.

    ``state`` is where the shaft is parked when the source is built, as ``(pin_a, pin_b)``.
    """

    def __init__(self, state=(1, 1), *, detent_steps: int = 4) -> None:
        self.pin_a = FakePin(state[0])
        self.pin_b = FakePin(state[1])
        self.source = MpEncoderSource(self.pin_a, self.pin_b, detent_steps=detent_steps)

    def move_to(self, state) -> None:
        """Put both pins at ``state`` and raise one interrupt for the change."""
        moved = self.pin_a if self.pin_a.level != state[0] else self.pin_b
        self.pin_a.level = state[0]
        self.pin_b.level = state[1]
        moved.fire()

    def turn(self, steps: int) -> None:
        """Turn the shaft ``steps`` quadrature steps, negative the other way round."""
        direction = 1 if steps >= 0 else -1
        for _ in range(abs(steps)):
            at = FORWARD_CYCLE.index((self.pin_a.level, self.pin_b.level))
            self.move_to(FORWARD_CYCLE[(at + direction) % len(FORWARD_CYCLE)])

    def counted(self) -> int:
        """Poll the source the way a loop tick does, and return the detents it published."""
        self.source.poll(0)
        return self.source.raw_position

    def banked(self) -> int:
        """Return the quadrature steps standing toward the detent in progress."""
        return self.source._counters[BANKED_STEPS]

    def slots(self) -> tuple:
        """Return the whole counter array, which is the only state an interrupt may write."""
        return tuple(self.source._counters)
