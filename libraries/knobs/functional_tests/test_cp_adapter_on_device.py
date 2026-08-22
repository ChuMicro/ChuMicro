"""On-device tests for the CircuitPython knob sources against real firmware.

Runs only on CircuitPython boards.  The module-level ``__chumicro_runtimes__`` marker tells
the pytest-device plugin to skip the wrong-runtime parametrization, so MP boards never try
to import the file.

Nothing here turns a shaft or sweeps a wiper, because CircuitPython gives ``rotaryio`` and
``analogio`` exclusive ownership of their pins: no second object can drive the pin a source
already holds, so edges cannot be produced from the chip the way the MicroPython suite
produces them.  What these cover is the contract with the firmware underneath, which is the
half a host test cannot reach: that the divisor this library asks for is one
``IncrementalEncoder`` accepts, that a converter reads inside the range the library assumes,
that both sources hand their pins back, and that a tick allocates nothing.

Turning a real encoder and sweeping a real potentiometer stay bench work.
"""

__chumicro_runtimes__ = ("circuitpython",)

import gc

import analogio
import board
import rotaryio
from chumicro_knobs import DEFAULT_STEPS, RAW_RANGE, AnalogKnob, Encoder

#: Pin names that usually have something soldered to them, skipped when hunting for a free
#: pin so a source does not fight an onboard peripheral for a pad.
_ATTACHED = (
    "LED", "NEOPIXEL", "NEOPIXEL_POWER", "DOTSTAR", "APA102", "BUTTON", "BOOT0",
    "SDA", "SCL", "TX", "RX", "MISO", "MOSI", "SCK", "CS", "VOLTAGE_MONITOR",
    "I2C_POWER", "SDIO", "DEBUG",
)


def _candidates():
    """Yield board pins worth trying, in a stable order, skipping attached ones."""
    for name in dir(board):
        if not name.startswith("_") and name not in _ATTACHED:
            yield getattr(board, name)


def _trailing_number(name: str) -> int:
    """Return the digits a pin name ends with, or -1 when it ends with none."""
    digits = ""
    index = len(name) - 1
    while index >= 0 and name[index].isdigit():
        digits = name[index] + digits
        index -= 1
    return int(digits) if digits else -1


def _free_quadrature_pins():
    """Return two pins ``rotaryio`` will watch together, or fail saying none were found.

    On RP2040 the two pins are read by one PIO state machine and have to be next to each
    other in GPIO numbering, so the pair matters and cannot be assembled a pin at a time.
    Candidates are therefore ordered by the number their name ends with and offered in
    neighbouring pairs, and the firmware is left to say which pair it will take.  Ports
    without the adjacency rule accept the first pair offered.
    """
    numbered = []
    for name in dir(board):
        if name.startswith("_") or name in _ATTACHED:
            continue
        number = _trailing_number(name)
        if number >= 0:
            numbered.append((number, getattr(board, name)))
    numbered.sort(key=lambda entry: entry[0])

    for index in range(len(numbered) - 1):
        pin_a = numbered[index][1]
        pin_b = numbered[index + 1][1]
        try:
            claim = rotaryio.IncrementalEncoder(pin_a, pin_b)
        except (ValueError, TypeError, RuntimeError):
            # Either pin may be spoken for, the two may be the same pad under different
            # names, or the port may want them adjacent and these are not.
            continue
        claim.deinit()
        return pin_a, pin_b
    raise AssertionError("no adjacent pair of free pins on this board for rotaryio")


def _free_analog_pin():
    """Return a pin with a converter behind it, or fail saying none were found."""
    for pin in _candidates():
        try:
            converter = analogio.AnalogIn(pin)
        except (ValueError, TypeError, RuntimeError):
            continue
        converter.deinit()
        return pin
    raise AssertionError("no analog-capable free pin on this board")


# -- the divisor this library asks the firmware for --


def test_every_detent_size_is_a_divisor_rotaryio_accepts() -> None:
    """``detent_steps`` becomes ``divisor``, which is a firmware argument with its own rules.

    Four suits a panel-mount encoder that clicks once per quadrature cycle and one suits a
    smooth shaft, so both ends have to build.
    """
    pin_a, pin_b = _free_quadrature_pins()

    for detent_steps in (1, 2, 4, 8):
        encoder = rotaryio.IncrementalEncoder(pin_a, pin_b, divisor=detent_steps)
        assert encoder.divisor == detent_steps
        encoder.deinit()


# -- building on real pins --


def test_an_encoder_builds_on_two_real_pins_and_starts_at_zero() -> None:
    """A shaft nobody has turned reports no position and no movement.

    ``position`` counts detents from where the program started rather than reporting an
    angle, so zero at construction is the contract and not an accident of the hardware.
    """
    pin_a, pin_b = _free_quadrature_pins()
    encoder = Encoder(pin_a, pin_b)
    try:
        encoder.check(0)

        assert encoder.position == 0
        assert encoder.delta == 0
        assert encoder.just_moved is False
    finally:
        encoder.deinit()


def test_a_still_shaft_reports_nothing_however_often_it_is_checked() -> None:
    """Ticking a parked encoder never invents a detent, which is what a quiet loop sees."""
    pin_a, pin_b = _free_quadrature_pins()
    encoder = Encoder(pin_a, pin_b)
    try:
        moved = False
        for tick in range(200):
            if encoder.check(tick):
                moved = True

        assert moved is False
        assert encoder.position == 0
    finally:
        encoder.deinit()


def test_a_knob_builds_on_a_real_converter_and_reads_inside_its_range() -> None:
    """A real conversion lands in the 0 to 65535 window the step maths assumes.

    ``AnalogIn.value`` is scaled up by the firmware when the converter underneath is
    narrower, so a board with a 12 bit converter still reports full scale.  A reading
    outside this would silently push ``value`` past the last step.
    """
    knob = AnalogKnob(_free_analog_pin())
    try:
        knob.check(0)

        assert 0 <= knob.raw < RAW_RANGE
        assert 0 <= knob.value < DEFAULT_STEPS
    finally:
        knob.deinit()


# -- letting go --


def test_deinit_hands_both_quadrature_pins_back() -> None:
    """A released encoder can be rebuilt, which a leaked pin would prevent."""
    pin_a, pin_b = _free_quadrature_pins()

    for _ in range(3):
        encoder = Encoder(pin_a, pin_b)
        encoder.check(0)

        assert encoder.position == 0

        encoder.deinit()


def test_deinit_hands_the_converter_pin_back() -> None:
    """A released knob can be rebuilt on the same pin."""
    pin = _free_analog_pin()

    for _ in range(3):
        knob = AnalogKnob(pin)
        knob.check(0)

        assert 0 <= knob.raw < RAW_RANGE

        knob.deinit()


# -- what a tick costs --


def test_a_quiet_encoder_tick_allocates_nothing() -> None:
    """The heap does not grow across a thousand checks of a still shaft."""
    pin_a, pin_b = _free_quadrature_pins()
    encoder = Encoder(pin_a, pin_b)
    try:
        for tick in range(200):
            encoder.check(tick)

        gc.collect()
        before = gc.mem_alloc()
        for tick in range(1000):
            encoder.check(tick)

        assert gc.mem_alloc() - before == 0
    finally:
        encoder.deinit()


def test_a_knob_tick_allocates_nothing() -> None:
    """Sampling a converter every tick does not grow the heap either."""
    knob = AnalogKnob(_free_analog_pin())
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
