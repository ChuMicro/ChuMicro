"""Pins and buses by MCU GPIO number, the same numbers on both device runtimes.

The wire between a board and a part has one identity, the GPIO number,
and each runtime spells it differently: ``machine.Pin(6)`` on
MicroPython, ``board.GP6`` or ``board.IO6`` on CircuitPython.  The
resolvers here take the number and return what the runtime's own API
takes, so an app's construction block carries wiring facts and nothing
runtime-specific.

Every resolver also accepts the runtime's own pin object in place of
a number, for a port whose pins are not a flat integer (stm32's ``PA5``),
and every bus resolver returns an already-constructed bus unchanged.
"""

import sys

_RUNTIME = sys.implementation.name
_NO_GPIO = "GPIO resolution needs MicroPython or CircuitPython; inject a fake on "


class _OutputLine:
    """A ``digitalio.DigitalInOut`` behind the callable pin protocol.

    ``line(1)`` drives high, ``line(0)`` drives low, and ``line()`` reads
    the level back, which is what ``machine.Pin`` does when called.
    """

    def __init__(self, line: object) -> None:
        self._line = line

    def __call__(self, value: int | None = None) -> int | None:
        if value is None:
            return 1 if self._line.value else 0
        self._line.value = bool(value)
        return None


def gpio_pin(pin: object) -> object:
    """Return the runtime's own pin object for GPIO ``pin``.

    This is the pin identity an API takes when it drives the pin itself:
    ``machine.Pin(n)`` on MicroPython, ``microcontroller.pin.GPIOn`` on
    CircuitPython, which is what ``fourwire.FourWire`` wants for its
    command, chip-select, and reset lines.  A pin object is returned
    as given.

    Raises:
        RuntimeError: On a runtime without GPIO, such as CPython.
        ValueError: When no pin with that number exists on this board.
    """
    if not isinstance(pin, int):
        return pin
    if _RUNTIME == "micropython":
        from machine import Pin

        return Pin(pin)
    if _RUNTIME == "circuitpython":
        import microcontroller

        found = getattr(microcontroller.pin, f"GPIO{pin}", None)
        if found is None:
            raise ValueError(f"GPIO{pin} is not a pin on this board")
        return found
    raise RuntimeError(_NO_GPIO + _RUNTIME)


def digital_output(pin: object, *, value: int = 0) -> object:
    """Return a callable output pin on GPIO ``pin``, driven to ``value`` now.

    The result satisfies the pin protocol chumicro drivers take:
    ``pin(1)`` drives high, ``pin(0)`` drives low, ``pin()`` reads back.

    Args:
        pin: The MCU GPIO number, or the runtime's own pin object.  On
            MicroPython a ``machine.Pin`` is returned as it was given,
            mode and all; on CircuitPython a ``microcontroller.Pin`` is
            wrapped the same way a number is.
        value: The level to drive at construction, 0 or 1.  A chip
            select idles at 1, a data/command line at 0.

    Raises:
        RuntimeError: On a runtime without GPIO, such as CPython.
        ValueError: When no pin with that number exists on this board.
    """
    if _RUNTIME == "micropython":
        from machine import Pin

        if isinstance(pin, int):
            return Pin(pin, Pin.OUT, value=value)
        return pin
    if _RUNTIME == "circuitpython":
        import digitalio

        line = digitalio.DigitalInOut(gpio_pin(pin))
        line.switch_to_output(value=bool(value))
        return _OutputLine(line)
    raise RuntimeError(_NO_GPIO + _RUNTIME)


def spi_bus(controller: object, *, sck: object, mosi: object,
            miso: object | None = None, baudrate: int = 1_000_000,
            polarity: int = 0, phase: int = 0) -> object:
    """Return the runtime's SPI bus on the given GPIO numbers.

    MicroPython gets ``machine.SPI`` and CircuitPython gets ``busio.SPI``
    configured to ``baudrate``, ``polarity``, and ``phase``, so a driver
    that only writes needs no further setup on either.  A CircuitPython
    consumer that reconfigures the bus itself, ``fourwire.FourWire``
    for one, still takes its own baudrate.

    Args:
        controller: The MicroPython SPI controller id, ``SPI(0)`` or
            ``SPI(1)`` on rp2 and ``SPI(1)`` or ``SPI(2)`` on esp32; the
            pins must belong to it.  CircuitPython derives the controller
            from the pins and ignores the id.  An already-constructed bus
            is returned unchanged.
        sck: Clock GPIO number, or the runtime's pin object.
        mosi: Controller-out GPIO number, or the runtime's pin object.
        miso: Controller-in GPIO number, or None for a write-only part,
            which leaves the runtime's own default in place.
        baudrate: Clock rate in Hz.
        polarity: Clock idle level, 0 or 1.
        phase: Sampling edge, 0 for the first and 1 for the second.

    Raises:
        RuntimeError: On a runtime without GPIO, such as CPython.
        ValueError: When a number names no pin on this board, or a pin
            cannot serve that role on the named controller.
    """
    if not isinstance(controller, int):
        return controller
    if _RUNTIME == "micropython":
        from machine import SPI

        if miso is None:
            return SPI(controller, baudrate=baudrate, polarity=polarity,
                       phase=phase, sck=gpio_pin(sck), mosi=gpio_pin(mosi))
        return SPI(controller, baudrate=baudrate, polarity=polarity,
                   phase=phase, sck=gpio_pin(sck), mosi=gpio_pin(mosi),
                   miso=gpio_pin(miso))
    if _RUNTIME == "circuitpython":
        import busio

        bus = busio.SPI(gpio_pin(sck), MOSI=gpio_pin(mosi),
                        MISO=None if miso is None else gpio_pin(miso))
        while not bus.try_lock():
            pass
        bus.configure(baudrate=baudrate, polarity=polarity, phase=phase)
        bus.unlock()
        return bus
    raise RuntimeError(_NO_GPIO + _RUNTIME)


def i2c_bus(controller: object, *, scl: object, sda: object,
            frequency: int = 400_000) -> object:
    """Return the runtime's I2C bus on the given GPIO numbers.

    MicroPython gets ``machine.I2C`` and CircuitPython gets ``busio.I2C``,
    both at ``frequency``; the default is the same on both runtimes
    rather than each one's own.

    Args:
        controller: The MicroPython I2C controller id, whose pins must
            belong to it.  CircuitPython derives the controller from the
            pins and ignores the id.  An already-constructed bus is
            returned unchanged.
        scl: Clock GPIO number, or the runtime's pin object.
        sda: Data GPIO number, or the runtime's pin object.
        frequency: Bus clock in Hz.  A PCF8574 backpack wants 100_000.

    Raises:
        RuntimeError: On a runtime without GPIO, such as CPython.
        ValueError: When a number names no pin on this board, or a pin
            cannot serve that role on the named controller.
    """
    if not isinstance(controller, int):
        return controller
    if _RUNTIME == "micropython":
        from machine import I2C

        return I2C(controller, scl=gpio_pin(scl), sda=gpio_pin(sda),
                   freq=frequency)
    if _RUNTIME == "circuitpython":
        import busio

        return busio.I2C(gpio_pin(scl), gpio_pin(sda), frequency=frequency)
    raise RuntimeError(_NO_GPIO + _RUNTIME)
