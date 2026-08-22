"""Host-lane tests for the MicroPython sources: the ring depth and the clock they judge by.

``machine`` is stubbed into ``sys.modules`` for the length of each construction, so
the two sources can be built and driven on a laptop.  What that buys is the one
property a board test cannot show cheaply: which clock a settle window is measured
against.  Every test here injects a clock that disagrees with wrap-safe tick
arithmetic and asserts the source followed the injected one.  Real pins, real
interrupt latency, and real bounce stay in ``functional_tests/``.

The module under test is MicroPython-marked, so a CircuitPython deploy never carries
it; this file stays on the host lane where importing it always resolves.
"""

#: Host-lane only: imports a MicroPython-marked module, which a CircuitPython
#: deploy does not carry.  Never staged to a device.
__chumicro_host_only__ = True

import sys

from chumicro_buttons._adapters.mp import (
    DEFAULT_RING_DEPTH,
    MpButtonSource,
    MpKeyMatrixSource,
)
from chumicro_test_harness import raises
from chumicro_test_harness.patching import FakeModule, SwapItem
from chumicro_timing.ticks import ticks_diff

#: Settle window every source here is built with.
SETTLE_MS = 20

#: Where the injected clock starts.  Past the 2**29 tick ring wrap-safe arithmetic
#: folds readings into, so a value taken from this clock could not have come from
#: the wrap-safe one.
CLOCK_START_MS = 600_000_000

#: A gap the two arithmetics answer differently: four days, which is longer than half
#: the 2**29 ring.  Plain subtraction calls it elapsed; the folding compare aliases it
#: to a negative, meaning "keep waiting".
DISAGREEING_GAP_MS = 4 * 86_400_000


class UnwrappedTicks:
    """A clock that disagrees with wrap-safe tick arithmetic, on purpose.

    Its readings start past the 2**29 ring wrap-safe arithmetic folds into, and its
    ``ticks_diff`` plainly subtracts instead of folding.  A span longer than half that
    ring therefore reads as elapsed here and as still pending under the folding
    compare, so a source that judged a window with anything but this object answers
    the opposite way.
    """

    def __init__(self, start_ms: int = CLOCK_START_MS) -> None:
        self.now_ms = start_ms

    def ticks_ms(self) -> int:
        """Return the reading, which only changes when a test assigns ``now_ms``."""
        return self.now_ms

    def ticks_add(self, ticks_value: int, delta: int) -> int:
        """Return ``ticks_value + delta``, with no ring to fold it into."""
        return ticks_value + delta

    def ticks_diff(self, end: int, start: int) -> int:
        """Return ``end - start``, with no aliasing at any distance."""
        return end - start


class FakePin:
    """One ``machine.Pin`` a test drives by hand: it reports a level and holds an IRQ.

    ``level`` is what the pin reads and a test assigns it directly.  ``fire`` moves the
    pin and runs whatever handler was installed on it, which is how a test stands in
    for the interrupt a real edge would raise.
    """

    IN = 0
    OUT = 1
    PULL_UP = 2
    PULL_DOWN = 3
    IRQ_RISING = 4
    IRQ_FALLING = 8

    def __init__(self, level: int = 1) -> None:
        self.level = level
        self.mode = None
        self.handler = None

    def init(self, mode, pull=None, value=None) -> None:
        """Take the direction, and the driven level when one is given."""
        self.mode = mode
        if value is not None:
            self.level = value

    def value(self) -> int:
        """Return what this pin currently reads."""
        return self.level

    def irq(self, handler=None, trigger=0, hard=False) -> None:
        """Install (or with ``handler=None`` remove) the edge handler."""
        self.handler = handler

    def fire(self, level: int) -> None:
        """Move the pin to ``level`` and run the handler installed on it."""
        self.level = level
        self.handler(self)


def _fake_machine() -> FakeModule:
    """Return a ``machine`` stand-in whose ``Pin`` is the hand-driven fake."""
    machine = FakeModule()
    machine.Pin = FakePin
    return machine


def test_the_capture_ring_holds_a_full_press_and_release_of_bounce() -> None:
    """The default ring is 32 slots, enough for both bounce bursts of one tap."""
    assert DEFAULT_RING_DEPTH == 32


def test_the_two_arithmetics_answer_the_four_day_gap_differently() -> None:
    """The injected clock calls the gap elapsed and the folding compare calls it pending.

    This is what makes the two tests below meaningful rather than tautological: a
    source reaching for wrap-safe arithmetic instead of the clock it was handed gets
    the opposite answer, not a slightly different one.
    """
    clock = UnwrappedTicks()
    late_ms = CLOCK_START_MS + DISAGREEING_GAP_MS

    assert clock.ticks_diff(late_ms, CLOCK_START_MS) > SETTLE_MS
    assert ticks_diff(late_ms, CLOCK_START_MS) < 0


def test_the_capture_source_judges_its_settle_window_by_the_clock_it_was_given() -> None:
    """A press held past the window is published, timed and stamped by the injected clock.

    The window is still shut five milliseconds in, and open once the four-day gap has
    passed, which only the injected clock says.  The published ``event_ms`` is the
    reading the interrupt stamped the edge with, so it shows the capture handler read
    that same clock rather than one of its own.
    """
    clock = UnwrappedTicks()
    pin = FakePin(level=1)
    with SwapItem(sys.modules, "machine", _fake_machine()):
        source = MpButtonSource((pin,), active_low=True, settle_ms=SETTLE_MS, ticks=clock)

    pin.fire(0)

    source.poll(CLOCK_START_MS + 5)
    assert source.next_event() is False

    source.poll(CLOCK_START_MS + DISAGREEING_GAP_MS)
    assert source.next_event() is True
    assert source.event_key == 0
    assert source.event_pressed is True
    assert source.event_ms == CLOCK_START_MS


def test_the_matrix_scan_judges_its_settle_window_by_the_clock_it_was_given() -> None:
    """A key held past the window is published, timed by the injected clock.

    One row of two columns, with the second column pulled to the driven level, is key
    1 held down.  The scan reports nothing on the tick that first saw it and reports
    the press once the four-day gap has passed, which only the injected clock says.
    """
    clock = UnwrappedTicks()
    row = FakePin(level=1)
    columns = (FakePin(level=1), FakePin(level=0))
    with SwapItem(sys.modules, "machine", _fake_machine()):
        source = MpKeyMatrixSource(
            (row,),
            columns,
            columns_to_anodes=True,
            settle_ms=SETTLE_MS,
            ticks=clock,
        )

    source.poll(CLOCK_START_MS)
    assert source.next_event() is False

    source.poll(CLOCK_START_MS + DISAGREEING_GAP_MS)
    assert source.next_event() is True
    assert source.event_key == 1
    assert source.event_pressed is True
    assert source.event_ms == CLOCK_START_MS


def test_neither_source_builds_without_a_clock() -> None:
    """Omitting ticks= raises TypeError from both sources.

    Neither has a clock of its own to fall back on, which is what keeps a settle
    window and the durations the caller reads on one time base.
    """
    with SwapItem(sys.modules, "machine", _fake_machine()):
        with raises(TypeError):
            MpButtonSource((FakePin(),), active_low=True, settle_ms=SETTLE_MS)

        with raises(TypeError):
            MpKeyMatrixSource((FakePin(),), (FakePin(),), settle_ms=SETTLE_MS)
