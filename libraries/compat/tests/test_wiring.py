"""Host-only tests for the GPIO-number resolvers.

Each test points the module's runtime name at the branch under test
and installs fake ``machine``, ``microcontroller``, ``digitalio``, and
``busio`` modules in ``sys.modules``, so both device branches run on
every host interpreter and never need real silicon.
"""

__chumicro_host_only__ = True

import sys

from chumicro_compat import wiring
from chumicro_test_harness import raises
from chumicro_test_harness.patching import FakeModule, SwapAttribute, SwapItem


class _FakeMachinePin:
    OUT = "out"

    def __init__(self, number: int, mode: object = None, *, value: object = None) -> None:
        self.number = number
        self.mode = mode
        self.value = value


class _FakeMachineBus:
    def __init__(self, controller: int, **keywords: object) -> None:
        self.controller = controller
        self.keywords = keywords


def _fake_machine() -> FakeModule:
    module = FakeModule()
    module.Pin = _FakeMachinePin
    module.SPI = _FakeMachineBus
    module.I2C = _FakeMachineBus
    return module


class _McuPin:
    def __init__(self, name: str) -> None:
        self.name = name


def _fake_microcontroller() -> FakeModule:
    pins = FakeModule()
    for number in (4, 5, 6, 7):
        setattr(pins, f"GPIO{number}", _McuPin(f"GPIO{number}"))
    module = FakeModule()
    module.pin = pins
    return module


class _FakeDigitalInOut:
    instances = []

    def __init__(self, pin: object) -> None:
        self.pin = pin
        self.value = False
        self.output_value = None
        _FakeDigitalInOut.instances.append(self)

    def switch_to_output(self, *, value: bool) -> None:
        self.output_value = value
        self.value = value


def _fake_digitalio() -> FakeModule:
    del _FakeDigitalInOut.instances[:]
    module = FakeModule()
    module.DigitalInOut = _FakeDigitalInOut
    return module


class _FakeBusioSpi:
    def __init__(self, clock: object, MOSI: object = None, MISO: object = None) -> None:  # noqa: N803 - busio's own keyword names
        self.clock = clock
        self.mosi = MOSI
        self.miso = MISO
        self.locked = False
        self.lock_attempts = 0
        self.configured = None

    def try_lock(self) -> bool:
        self.lock_attempts += 1
        if self.lock_attempts == 1:
            return False
        self.locked = True
        return True

    def configure(self, *, baudrate: int, polarity: int, phase: int) -> None:
        assert self.locked, "configure() outside the lock"
        self.configured = (baudrate, polarity, phase)

    def unlock(self) -> None:
        self.locked = False


class _FakeBusioI2c:
    def __init__(self, scl: object, sda: object, *, frequency: int) -> None:
        self.scl = scl
        self.sda = sda
        self.frequency = frequency


def _fake_busio() -> FakeModule:
    module = FakeModule()
    module.SPI = _FakeBusioSpi
    module.I2C = _FakeBusioI2c
    return module


class _Runtime:
    """Enter a runtime name with its fake hardware modules installed."""

    def __init__(self, name: str) -> None:
        self._swaps = [SwapAttribute(wiring, "_RUNTIME", name)]
        if name == "micropython":
            self._swaps.append(SwapItem(sys.modules, "machine", _fake_machine()))
        if name == "circuitpython":
            self._swaps.append(SwapItem(sys.modules, "microcontroller", _fake_microcontroller()))
            self._swaps.append(SwapItem(sys.modules, "digitalio", _fake_digitalio()))
            self._swaps.append(SwapItem(sys.modules, "busio", _fake_busio()))

    def __enter__(self) -> object:
        for swap in self._swaps:
            swap.__enter__()
        return self

    def __exit__(self, exc_type: object, exc_value: object, exc_traceback: object) -> bool:
        index = len(self._swaps)
        while index > 0:
            index -= 1
            self._swaps[index].__exit__(exc_type, exc_value, exc_traceback)
        return False


def test_gpio_pin_micropython_constructs_a_bare_pin() -> None:
    with _Runtime("micropython"):
        pin = wiring.gpio_pin(6)
    assert isinstance(pin, _FakeMachinePin)
    assert (pin.number, pin.mode, pin.value) == (6, None, None)


def test_gpio_pin_circuitpython_looks_up_the_mcu_pin() -> None:
    with _Runtime("circuitpython"):
        assert wiring.gpio_pin(7).name == "GPIO7"


def test_gpio_pin_passes_a_pin_object_through() -> None:
    given = _McuPin("PA5")
    with _Runtime("circuitpython"):
        assert wiring.gpio_pin(given) is given


def test_gpio_pin_without_gpio_names_the_runtime() -> None:
    with _Runtime("cpython"), raises(RuntimeError, match="cpython"):
        wiring.gpio_pin(6)


def test_digital_output_micropython_constructs_an_output_pin_at_value() -> None:
    with _Runtime("micropython"):
        pin = wiring.digital_output(5, value=1)
    assert isinstance(pin, _FakeMachinePin)
    assert (pin.number, pin.mode, pin.value) == (5, "out", 1)


def test_digital_output_micropython_passes_a_pin_object_through() -> None:
    given = _FakeMachinePin(9)
    with _Runtime("micropython"):
        assert wiring.digital_output(given) is given


def test_digital_output_circuitpython_is_callable_over_a_digitalinout() -> None:
    with _Runtime("circuitpython"):
        pin = wiring.digital_output(6, value=1)
    line = _FakeDigitalInOut.instances[0]
    assert line.pin.name == "GPIO6"
    assert line.output_value is True
    assert pin() == 1
    pin(0)
    assert line.value is False
    assert pin() == 0


def test_digital_output_circuitpython_accepts_a_pin_object() -> None:
    given = _McuPin("PA5")
    with _Runtime("circuitpython"):
        wiring.digital_output(given)
    assert _FakeDigitalInOut.instances[0].pin is given


def test_digital_output_circuitpython_names_a_missing_gpio() -> None:
    with _Runtime("circuitpython"), raises(ValueError, match="GPIO99"):
        wiring.digital_output(99)


def test_digital_output_without_gpio_names_the_runtime() -> None:
    with _Runtime("cpython"), raises(RuntimeError, match="cpython"):
        wiring.digital_output(5)


def test_spi_bus_micropython_names_the_controller_and_pins() -> None:
    with _Runtime("micropython"):
        bus = wiring.spi_bus(1, sck=7, mosi=11, miso=3, baudrate=40_000_000)
    assert bus.controller == 1
    assert (bus.keywords["sck"].number, bus.keywords["mosi"].number) == (7, 11)
    assert bus.keywords["miso"].number == 3
    assert bus.keywords["baudrate"] == 40_000_000
    assert (bus.keywords["polarity"], bus.keywords["phase"]) == (0, 0)


def test_spi_bus_micropython_leaves_miso_to_the_port_when_none() -> None:
    with _Runtime("micropython"):
        bus = wiring.spi_bus(0, sck=6, mosi=7)
    assert "miso" not in bus.keywords


def test_spi_bus_micropython_passes_pin_objects_through() -> None:
    sck = _FakeMachinePin(6)
    with _Runtime("micropython"):
        bus = wiring.spi_bus(0, sck=sck, mosi=7)
    assert bus.keywords["sck"] is sck


def test_spi_bus_circuitpython_configures_under_the_lock() -> None:
    with _Runtime("circuitpython"):
        bus = wiring.spi_bus(0, sck=6, mosi=7, baudrate=40_000_000, phase=1)
    assert (bus.clock.name, bus.mosi.name, bus.miso) == ("GPIO6", "GPIO7", None)
    assert bus.configured == (40_000_000, 0, 1)
    assert bus.lock_attempts == 2
    assert bus.locked is False


def test_spi_bus_circuitpython_resolves_miso_when_given() -> None:
    with _Runtime("circuitpython"):
        bus = wiring.spi_bus(0, sck=6, mosi=7, miso=4)
    assert bus.miso.name == "GPIO4"


def test_spi_bus_returns_a_constructed_bus_unchanged() -> None:
    given = object()
    with _Runtime("micropython"):
        assert wiring.spi_bus(given, sck=6, mosi=7) is given


def test_spi_bus_without_gpio_names_the_runtime() -> None:
    with _Runtime("cpython"), raises(RuntimeError, match="cpython"):
        wiring.spi_bus(0, sck=6, mosi=7)


def test_i2c_bus_micropython_uses_the_freq_keyword() -> None:
    with _Runtime("micropython"):
        bus = wiring.i2c_bus(0, scl=5, sda=4, frequency=100_000)
    assert bus.controller == 0
    assert (bus.keywords["scl"].number, bus.keywords["sda"].number) == (5, 4)
    assert bus.keywords["freq"] == 100_000


def test_i2c_bus_circuitpython_passes_scl_then_sda() -> None:
    with _Runtime("circuitpython"):
        bus = wiring.i2c_bus(0, scl=5, sda=4, frequency=100_000)
    assert (bus.scl.name, bus.sda.name, bus.frequency) == ("GPIO5", "GPIO4", 100_000)


def test_i2c_bus_default_frequency_is_the_same_on_both_runtimes() -> None:
    with _Runtime("micropython"):
        micropython_bus = wiring.i2c_bus(0, scl=5, sda=4)
    with _Runtime("circuitpython"):
        circuitpython_bus = wiring.i2c_bus(0, scl=5, sda=4)
    assert micropython_bus.keywords["freq"] == circuitpython_bus.frequency == 400_000


def test_i2c_bus_returns_a_constructed_bus_unchanged() -> None:
    given = object()
    with _Runtime("circuitpython"):
        assert wiring.i2c_bus(given, scl=5, sda=4) is given


def test_i2c_bus_without_gpio_names_the_runtime() -> None:
    with _Runtime("cpython"), raises(RuntimeError, match="cpython"):
        wiring.i2c_bus(0, scl=5, sda=4)
