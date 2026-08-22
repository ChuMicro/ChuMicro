"""On-device tests for ``MpButtonSource`` against a real ``Pin.irq``.

Runs only on MicroPython boards.  The module-level ``__chumicro_runtimes__`` marker tells
the pytest-device plugin to skip the wrong-runtime parametrization, so CP boards never try
to import the file.

MicroPython has no background key scanner, so unlike the CircuitPython side this library
owns the capture itself: an interrupt per pin, a preallocated ring, and a settle window
spent on the tick.  That is the part worth proving on silicon, and it needs edges.

The edges come from the chip rather than a finger.  A GPIO driven as an output raises its
own input interrupt, so a second ``Pin`` object on the same number can play the switch:
low is a press, high is a release, and the timing is exact instead of human.  Ports where
that does not hold skip rather than fail, because the trick is the instrument here and not
the thing under test.

Pins are driven, so the suite needs one with nothing attached to it.  It picks the first
candidate that can raise its own interrupt and leaves it as an input on the way out.
"""

__chumicro_runtimes__ = ("micropython",)

import gc
import time

import machine
from chumicro_buttons import Button
from chumicro_buttons._adapters.mp import DEFAULT_RING_DEPTH
from chumicro_test_harness import skip
from chumicro_timing import ticks, ticks_ms

#: GPIO numbers to try for a free, self-triggering pin.  Low numbers on rp2040, mid
#: numbers on esp32, skipping the strapping pins and the ones a board usually spends on
#: flash, USB, or the console.
_CANDIDATES = (5, 6, 7, 4, 14, 21, 22, 25, 26, 27, 32, 33)

#: Settle window these tests ask for.  Short enough that a test is not spent waiting and
#: long enough that a driven edge clears it with room over.
_SETTLE_MS = 20


def _self_triggering_pin():
    """Return a GPIO number whose own output edges raise its input interrupt."""
    for number in _CANDIDATES:
        try:
            watcher = machine.Pin(number, machine.Pin.IN, machine.Pin.PULL_UP)
        except (ValueError, TypeError):
            continue
        seen = []
        watcher.irq(
            handler=lambda pin, into=seen: into.append(1),
            trigger=machine.Pin.IRQ_RISING | machine.Pin.IRQ_FALLING,
        )
        driver = machine.Pin(number, machine.Pin.OUT)
        driver.value(0)
        time.sleep_ms(2)
        driver.value(1)
        time.sleep_ms(2)
        watcher.irq(handler=None)
        machine.Pin(number, machine.Pin.IN, machine.Pin.PULL_UP)
        if seen:
            return number
    skip("no self-triggering GPIO on this port, so edges cannot be driven from the chip")


class _Switch:
    """A driven GPIO standing in for a switch wired to ground, plus the button reading it.

    ``press`` and ``release`` move the pin the way contacts would.  ``bounce`` chatters it
    without settling, which is what a real contact does on the way to either state.
    """

    def __init__(self, number: int, **button_arguments) -> None:
        self._number = number
        self._driver = machine.Pin(number, machine.Pin.OUT)
        self._driver.value(1)
        self.button = Button(
            pin=machine.Pin(number), ticks=ticks, settle_ms=_SETTLE_MS, **button_arguments
        )
        self.source = self.button._source

    def press(self) -> None:
        """Pull the pin down, the way closing a switch to ground does."""
        machine.Pin(self._number, machine.Pin.OUT).value(0)

    def release(self) -> None:
        """Let the pin back up to its pull-up."""
        machine.Pin(self._number, machine.Pin.OUT).value(1)

    def bounce(self, times: int) -> None:
        """Chatter the contact ``times`` over, far faster than the settle window."""
        driver = machine.Pin(self._number, machine.Pin.OUT)
        for _ in range(times):
            driver.value(0)
            driver.value(1)

    def settle(self) -> None:
        """Wait out the settle window so the next tick can believe what it reads."""
        time.sleep_ms(_SETTLE_MS + 10)

    def tick(self) -> None:
        """Run one pass of the loop."""
        self.button.check(ticks_ms())

    def close(self) -> None:
        """Detach the interrupt and leave the pin an input."""
        self.button.deinit()
        machine.Pin(self._number, machine.Pin.IN, machine.Pin.PULL_UP)


# -- the interrupt, the ring, and the drain --


def test_the_interrupt_captures_a_press_and_the_release_after_it() -> None:
    """An edge raised while the loop is elsewhere still reaches the next tick.

    Nothing samples the pin here.  The press lands in the ring from interrupt context and
    the drain is what turns it into a reading, which is the whole MicroPython design.
    """
    switch = _Switch(_self_triggering_pin())
    try:
        switch.press()
        switch.settle()
        switch.tick()

        assert switch.button.just_pressed is True
        assert switch.button.pressed is True

        switch.release()
        switch.settle()
        switch.tick()

        assert switch.button.just_released is True
        assert switch.button.pressed is False
    finally:
        switch.close()


def test_a_press_is_stamped_with_when_it_happened_not_when_it_was_noticed() -> None:
    """A loop that comes back late reports the hold the person actually performed.

    The interrupt stamps the edge as it fires, so a stall between the press and the tick
    shows up in ``held_ms`` instead of being lost.
    """
    switch = _Switch(_self_triggering_pin())
    try:
        switch.press()
        time.sleep_ms(150)
        switch.tick()

        assert switch.button.just_pressed is True
        assert switch.button.held_ms >= 100
    finally:
        switch.close()


def test_chatter_that_never_settles_is_not_a_press() -> None:
    """A contact bouncing faster than the settle window produces no reading at all.

    This is the case the window exists for.  Every one of these edges reaches the ring, so
    the drain is what has to throw them away.
    """
    switch = _Switch(_self_triggering_pin())
    try:
        switch.bounce(8)
        switch.tick()

        assert switch.button.just_pressed is False
        assert switch.button.pressed is False
    finally:
        switch.close()


def test_a_press_arriving_through_bounce_still_lands_once() -> None:
    """Chatter followed by a held level is one press, not one per edge.

    A real contact bounces on the way closed, so the edges before the signal settles have
    to collapse into the single press the finger made.
    """
    switch = _Switch(_self_triggering_pin())
    try:
        switch.bounce(6)
        switch.press()
        switch.settle()

        presses = 0
        for _ in range(3):
            switch.tick()
            if switch.button.just_pressed:
                presses += 1

        assert presses == 1
    finally:
        switch.close()


# -- when edges outrun the drain --


def test_the_ring_says_so_when_it_drops_an_edge() -> None:
    """More edges than slots between two ticks raises ``overflowed`` for that tick.

    The ring is sized for the burst a bouncing contact makes, so reaching this needs many
    times that.  What matters is that the loss is reported rather than silently changing
    what the key reads.
    """
    switch = _Switch(_self_triggering_pin())
    try:
        switch.bounce(DEFAULT_RING_DEPTH * 2)
        switch.tick()

        assert switch.button.overflowed is True

        # The next drain re-reads the pin, so a dropped edge costs one tick and not a key
        # that reads pressed for good.
        switch.release()
        switch.settle()
        switch.tick()
        switch.tick()

        assert switch.button.pressed is False
    finally:
        switch.close()


def test_an_ordinary_press_stays_far_inside_the_ring() -> None:
    """A press and its bounce leave most of the ring unused, which is what sizes it.

    Measured on a Pi Pico W, ten hand presses of a switch with no debounce hardware put 68
    edges through the interrupt and never left more than four standing at one tick.
    """
    switch = _Switch(_self_triggering_pin())
    try:
        switch.press()
        switch.settle()
        backlog = (switch.source._write_index - switch.source._read_index) % DEFAULT_RING_DEPTH

        assert backlog < DEFAULT_RING_DEPTH // 2
    finally:
        switch.close()


# -- setting up and letting go --


def test_a_button_builds_on_a_real_pin_and_reads_released() -> None:
    """A key with its pull-up on and nothing pulling it down is not pressed."""
    number = _self_triggering_pin()
    machine.Pin(number, machine.Pin.IN, machine.Pin.PULL_UP)
    button = Button(pin=machine.Pin(number), ticks=ticks)
    try:
        button.check(ticks_ms())

        assert button.pressed is False
        assert button.overflowed is False
    finally:
        button.deinit()


def test_deinit_takes_the_interrupt_off_the_pin() -> None:
    """After teardown the pin can chatter as much as it likes and nothing is captured."""
    switch = _Switch(_self_triggering_pin())
    source = switch.source
    try:
        switch.button.deinit()
        write_index = source._write_index

        switch.bounce(6)

        assert source._write_index == write_index
    finally:
        machine.Pin(switch._number, machine.Pin.IN, machine.Pin.PULL_UP)


def test_a_quiet_tick_allocates_nothing() -> None:
    """The heap does not grow across a thousand checks, so a loop can tick forever."""
    switch = _Switch(_self_triggering_pin())
    try:
        for _ in range(200):
            switch.tick()

        gc.collect()
        before = gc.mem_alloc()
        for _ in range(1000):
            switch.tick()

        assert gc.mem_alloc() - before == 0
    finally:
        switch.close()
