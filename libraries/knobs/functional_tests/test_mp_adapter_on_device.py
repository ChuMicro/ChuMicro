"""On-device tests for the MicroPython knob sources against real pins and a real converter.

Runs only on MicroPython boards.  The module-level ``__chumicro_runtimes__`` marker tells
the pytest-device plugin to skip the wrong-runtime parametrization, so CP boards never try
to import the file.

MicroPython has no encoder peripheral binding, so unlike CircuitPython this library owns the
quadrature capture itself: an interrupt on both signal pins and a transition table.  That is
the part worth proving on silicon, and it needs edges.

The edges come from the chip rather than a shaft.  A GPIO driven as an output raises its own
input interrupt, so a second ``Pin`` on the same number can play one side of the encoder, and
two of them can walk the four-state cycle a real one produces.  Ports where that does not
hold skip rather than fail, because the trick is the instrument here and not the thing under
test.

The analog side cannot be driven the same way, because no board here can put a known voltage
on its own ADC pin.  What it covers is the contract with the converter: that a reading lands
in the range the step arithmetic assumes, that the pin comes back, and that a tick allocates
nothing.  A real potentiometer stays bench work.
"""

__chumicro_runtimes__ = ("micropython",)

import gc
import time

import machine
from chumicro_knobs import RAW_RANGE, AnalogKnob, Encoder
from chumicro_test_harness import skip

#: The four pin states one turn passes through, as ``(pin_a, pin_b)``, in the order a forward
#: turn produces them.  Neighbours differ in exactly one pin, which is what makes the pair a
#: quadrature signal and what lets a decode name a direction at all.
_FORWARD = ((1, 1), (0, 1), (0, 0), (1, 0))

#: GPIO numbers to try for free, self-triggering pins.  These are driven as outputs, so the
#: list has to hold on every chip this library runs on, and the dangerous numbers differ per
#: family: 6 to 11 are SPI flash on a classic esp32, 26 to 32 are flash and PSRAM on the S2
#: and S3, 16 and 17 are PSRAM on a WROVER or TinyPICO, and 19 and 20 are native USB on both
#: S-series parts.  Driving any of those does not raise, it resets the board.
_CANDIDATES = (5, 4, 13, 14, 18)

#: Pins to try for a converter.  26 to 28 are the only analog-capable ones on an rp2040,
#: while an esp32 takes a wide spread of low numbers.
_ANALOG_CANDIDATES = (26, 27, 28, 1, 2, 3, 4, 5, 9, 10)


def _self_triggering_pins():
    """Return two GPIO numbers whose own output edges raise their input interrupts."""
    found = []
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
            found.append(number)
            if len(found) == 2:
                return found[0], found[1]
    skip("no pair of self-triggering GPIOs on this port, so edges cannot be driven")


def _free_analog_pin():
    """Return a GPIO number with a converter behind it, or skip saying there is none."""
    for number in _ANALOG_CANDIDATES:
        try:
            converter = machine.ADC(machine.Pin(number))
            converter.read_u16()
        except (ValueError, TypeError, OSError):
            continue
        return number
    skip("no analog-capable pin on this board")


class _Shaft:
    """Two driven GPIOs standing in for an encoder, plus the Encoder watching them.

    ``turn`` walks the quadrature cycle a step at a time, which is what a real shaft does.
    ``jump`` moves both pins at once, which a real shaft cannot do and only noise produces.
    """

    def __init__(self, number_a, number_b, **encoder_arguments) -> None:
        self._number_a = number_a
        self._number_b = number_b
        self._at = 0
        self._drive(_FORWARD[0])
        self.encoder = Encoder(number_a, number_b, **encoder_arguments)

    def _drive(self, state) -> None:
        """Put both pins at ``state``, which raises whichever interrupts that changes."""
        machine.Pin(self._number_a, machine.Pin.OUT).value(state[0])
        machine.Pin(self._number_b, machine.Pin.OUT).value(state[1])

    def turn(self, steps: int) -> None:
        """Walk ``steps`` quadrature steps, negative the other way round."""
        direction = 1 if steps >= 0 else -1
        for _ in range(abs(steps)):
            self._at = (self._at + direction) % len(_FORWARD)
            self._drive(_FORWARD[self._at])
            time.sleep_ms(1)

    def jump(self) -> None:
        """Move both pins at once, which is the transition a turning shaft cannot make."""
        self._at = (self._at + 2) % len(_FORWARD)
        self._drive(_FORWARD[self._at])
        time.sleep_ms(1)

    def tick(self) -> None:
        """Run one pass of the loop."""
        self.encoder.check(0)

    def close(self) -> None:
        """Detach the interrupts and leave both pins as inputs."""
        self.encoder.deinit()
        machine.Pin(self._number_a, machine.Pin.IN, machine.Pin.PULL_UP)
        machine.Pin(self._number_b, machine.Pin.IN, machine.Pin.PULL_UP)


# -- the interrupt and the decode --


def test_a_forward_turn_counts_detents_up() -> None:
    """Twelve quadrature steps forward are three detents at the default divisor.

    Nothing samples the pins here.  Every step arrives as an interrupt and is folded by the
    transition table, which is the whole MicroPython design.
    """
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        shaft.turn(12)
        shaft.tick()

        assert shaft.encoder.position == 3
    finally:
        shaft.close()


def test_the_same_turn_backward_counts_them_down() -> None:
    """The identical run of steps the other way round lands three detents below zero."""
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        shaft.turn(-12)
        shaft.tick()

        assert shaft.encoder.position == -3
    finally:
        shaft.close()


def test_turning_back_to_where_it_started_ends_at_zero() -> None:
    """Out and back is a net zero, so no step is counted twice or dropped on a reversal."""
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        shaft.turn(8)
        shaft.turn(-8)
        shaft.tick()

        assert shaft.encoder.position == 0
    finally:
        shaft.close()


def test_a_shaft_rocking_on_one_boundary_invents_no_detents() -> None:
    """A shaft resting between detents and rocking one step each way counts nothing.

    Partial steps stay banked until a whole detent is earned, so every rock forward is undone
    by the rock back however long it goes on.  This is the worn-detent case.
    """
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        for _ in range(10):
            shaft.turn(1)
            shaft.turn(-1)
        shaft.tick()

        assert shaft.encoder.position == 0
    finally:
        shaft.close()


def test_both_pins_moving_at_once_reads_as_no_movement() -> None:
    """The transition a turning shaft cannot make counts nothing, because only noise makes it.

    There is no direction to read out of it: the shaft would be equally far around the cycle
    either way, and guessing one is how a dirty encoder invents detents.
    """
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        for _ in range(4):
            shaft.jump()
        shaft.tick()

        assert shaft.encoder.position == 0
    finally:
        shaft.close()


def test_a_smooth_shaft_counts_every_step() -> None:
    """``detent_steps=1`` reports each quadrature step, which is what a clickless shaft wants."""
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b, detent_steps=1)
    try:
        shaft.turn(7)
        shaft.tick()

        assert shaft.encoder.position == 7
    finally:
        shaft.close()


# -- setting up and letting go --


def test_an_encoder_builds_on_real_pins_and_starts_at_zero() -> None:
    """A shaft nobody has turned reports no position and no movement."""
    pin_a, pin_b = _self_triggering_pins()
    encoder = Encoder(pin_a, pin_b)
    try:
        encoder.check(0)

        assert encoder.position == 0
        assert encoder.just_moved is False
    finally:
        encoder.deinit()


def test_deinit_takes_the_interrupts_off_both_pins() -> None:
    """After teardown the pins can be driven as far as they like and nothing counts."""
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        shaft.encoder.deinit()

        shaft.turn(12)
        counters = shaft.encoder._source._counters

        assert counters[0] == 0
    finally:
        machine.Pin(pin_a, machine.Pin.IN, machine.Pin.PULL_UP)
        machine.Pin(pin_b, machine.Pin.IN, machine.Pin.PULL_UP)


def test_a_quiet_encoder_tick_allocates_nothing() -> None:
    """The heap does not grow across a thousand checks of a still shaft."""
    pin_a, pin_b = _self_triggering_pins()
    shaft = _Shaft(pin_a, pin_b)
    try:
        for _ in range(200):
            shaft.tick()

        gc.collect()
        before = gc.mem_alloc()
        for _ in range(1000):
            shaft.tick()

        assert gc.mem_alloc() - before == 0
    finally:
        shaft.close()


# -- the wiper --


def test_a_knob_builds_on_a_real_converter_and_reads_inside_its_range() -> None:
    """A real conversion lands in the window the step arithmetic assumes.

    ``read_u16`` stretches whatever width the converter has up to sixteen bits, so a 12-bit
    part reports the same range as a wider one.  A reading outside this would push ``value``
    past the last step.
    """
    knob = AnalogKnob(machine.Pin(_free_analog_pin()))
    try:
        knob.check(0)

        assert 0 <= knob.raw < RAW_RANGE
        assert 0 <= knob.value < 100
    finally:
        knob.deinit()


def test_a_knob_tick_allocates_nothing() -> None:
    """Sampling a converter every tick does not grow the heap either."""
    knob = AnalogKnob(machine.Pin(_free_analog_pin()))
    try:
        for tick in range(200):
            knob.check(tick)

        gc.collect()
        before = gc.mem_alloc()
        for tick in range(1000):
            knob.check(tick)

        assert gc.mem_alloc() - before == 0
    finally:
        knob.deinit()
