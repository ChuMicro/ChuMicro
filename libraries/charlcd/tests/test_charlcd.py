"""Cross-runtime tests for CharLcd and its two transports.

Plain asserts plus the harness ``raises()`` helper.  A
RecordingTransport captures every raw PCF8574 byte and the testing
decoders fold enable-pulse pairs back into HD44780 commands, so the
assertions read as protocol, not as golden byte lists.
"""

from chumicro_charlcd import (
    CharLcd,
    CircuitPythonTransport,
    MicropythonTransport,
)
from chumicro_charlcd.testing import (
    RecordingTransport,
    decode_bytes,
    decode_nibbles,
)
from chumicro_test_harness import raises

_REGISTER_SELECT = 0x01
_BACKLIGHT = 0x08


class SleepRecorder:
    def __init__(self) -> None:
        self.sleeps: list[int] = []

    def __call__(self, duration_ms: int) -> None:
        self.sleeps.append(duration_ms)


def make_lcd(**kwargs) -> tuple:
    transport = RecordingTransport()
    sleeps = SleepRecorder()
    lcd = CharLcd(transport, sleep_ms=sleeps, **kwargs)
    return lcd, transport, sleeps


class TestInit:
    def test_wake_up_dance_then_configuration(self) -> None:
        """Init forces 8-bit mode thrice, drops to 4-bit, then configures."""
        _lcd, transport, _sleeps = make_lcd()
        nibbles = decode_nibbles(transport.raw)
        assert nibbles[:4] == [(0, 0x3), (0, 0x3), (0, 0x3), (0, 0x2)]
        commands = decode_bytes(transport.raw[8:])
        assert commands == [
            (0, 0x28), (0, 0x08), (0, 0x01), (0, 0x06), (0, 0x0C)]

    def test_init_honors_the_slow_timings(self) -> None:
        """The power-on settle and the clear delay both reach the clock."""
        _lcd, _transport, sleeps = make_lcd()
        assert sleeps.sleeps[0] == 50
        assert 2 in sleeps.sleeps

    def test_backlight_defaults_on_in_every_byte(self) -> None:
        """Every init byte carries the backlight bit."""
        _lcd, transport, _sleeps = make_lcd()
        raw = transport.raw
        for byte_index in range(len(raw)):
            assert raw[byte_index] & _BACKLIGHT


class TestWrite:
    def test_write_positions_then_sends_text(self) -> None:
        """write() sets the DDRAM address, then sends the characters."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.write("Hi", row=1, column=3)
        assert decode_bytes(transport.raw) == [
            (0, 0x80 | 0x40 + 3),
            (_REGISTER_SELECT, ord("H")),
            (_REGISTER_SELECT, ord("i"))]

    def test_text_is_clipped_to_the_row_not_wrapped(self) -> None:
        """Characters past the row's end are dropped, and 16 minus column 10 leaves 6."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.write("X" * 30, column=10)
        data = [value for select, value in decode_bytes(transport.raw)
                if select]
        assert len(data) == 6

    def test_out_of_range_position_raises(self) -> None:
        """A row or column outside the panel geometry is refused."""
        lcd, _transport, _sleeps = make_lcd()
        with raises(ValueError):
            lcd.write("x", row=2)
        with raises(ValueError):
            lcd.write("x", column=16)

    def test_four_row_geometry_addresses_the_lower_rows(self) -> None:
        """A 20x4 panel's row 2 lands at DDRAM 0x14."""
        lcd, transport, _sleeps = make_lcd(columns=20, rows=4)
        del transport.raw[:]
        lcd.write("x", row=2)
        select, command = decode_bytes(transport.raw)[0]
        assert (select, command) == (0, 0x80 | 0x14)


class TestBacklight:
    def test_off_drops_the_bit_from_all_later_traffic(self) -> None:
        """After backlight=False, no byte carries the backlight bit."""
        lcd, transport, _sleeps = make_lcd()
        lcd.backlight = False
        del transport.raw[:]
        lcd.write("dim")
        assert lcd.backlight is False
        raw = transport.raw
        for byte_index in range(len(raw)):
            assert not raw[byte_index] & _BACKLIGHT

    def test_toggle_writes_immediately_without_latching(self) -> None:
        """A toggle lands as one data-less write and never strobes enable."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.backlight = False
        lcd.backlight = True
        assert transport.raw == [0x00, _BACKLIGHT]


class FakeLockingI2c:
    """The four-method surface of ``busio.I2C`` the CP transport uses."""

    def __init__(self) -> None:
        self.writes: list = []
        self.locked = False
        self.lock_count = 0
        self.unlock_count = 0

    def try_lock(self) -> bool:
        self.lock_count += 1
        self.locked = True
        return True

    def unlock(self) -> None:
        self.unlock_count += 1
        self.locked = False

    def writeto(self, address: int, buffer: object) -> None:
        assert self.locked, "writeto outside the lock"
        self.writes.append((address, bytes(buffer)))


class FakeMachineI2c:
    """The one-method surface of ``machine.I2C`` the MP transport uses."""

    def __init__(self) -> None:
        self.writes: list = []

    def writeto(self, address: int, buffer: object) -> None:
        self.writes.append((address, bytes(buffer)))


class TestCircuitPythonTransport:
    def test_writes_one_byte_to_the_backpack_address(self) -> None:
        """One write_byte lands one byte at the default address."""
        bus = FakeLockingI2c()
        CircuitPythonTransport(bus).write_byte(0xA5)
        assert bus.writes == [(0x27, b"\xa5")]

    def test_lock_is_released_per_write(self) -> None:
        """Each write locks and unlocks once, so sensors can interleave."""
        bus = FakeLockingI2c()
        transport = CircuitPythonTransport(bus, address=0x3F)
        transport.write_byte(1)
        transport.write_byte(2)
        assert bus.lock_count == 2
        assert bus.unlock_count == 2
        assert not bus.locked
        assert [address for address, _data in bus.writes] == [0x3F, 0x3F]


class TestMicropythonTransport:
    def test_writes_one_byte_to_the_backpack_address(self) -> None:
        """One write_byte lands one byte at the default address."""
        bus = FakeMachineI2c()
        MicropythonTransport(bus).write_byte(0x5A)
        assert bus.writes == [(0x27, b"\x5a")]

    def test_alternate_address_is_used(self) -> None:
        """The A-suffix backpack address reaches every write."""
        bus = FakeMachineI2c()
        transport = MicropythonTransport(bus, address=0x3F)
        transport.write_byte(1)
        assert bus.writes == [(0x3F, b"\x01")]


def test_default_clock_construction() -> None:
    """Without sleep_ms=, construction runs on the real clock and inits."""
    transport = RecordingTransport()
    lcd = CharLcd(transport)
    assert lcd.backlight is True
    assert len(transport.raw) > 0
