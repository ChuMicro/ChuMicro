"""Cross-runtime tests for CharLcd and its two transports.

Plain asserts plus the harness ``raises()`` helper.  A
RecordingTransport captures every raw PCF8574 byte and the testing
decoders fold enable-pulse pairs back into HD44780 commands, so the
assertions read as protocol, not as golden byte lists.
"""

from chumicro_charlcd import (
    CharLcd,
    CircuitPythonTransport,
    MicroPythonTransport,
)
from chumicro_charlcd.testing import (
    BACKLIGHT,
    REGISTER_SELECT,
    RecordingTransport,
    decode_bytes,
    decode_nibbles,
)
from chumicro_test_harness import raises

#: Four mode-force nibbles, two bus writes each, open every init stream.
_MODE_FORCE_WRITES = 8


def make_lcd(**kwargs) -> tuple:
    transport = RecordingTransport()
    sleeps = []
    lcd = CharLcd(transport, sleep_ms=sleeps.append, **kwargs)
    return lcd, transport, sleeps


class TestInit:
    def test_wake_up_dance_then_configuration(self) -> None:
        """Init forces 8-bit mode thrice, drops to 4-bit, then configures."""
        _lcd, transport, _sleeps = make_lcd()
        nibbles = decode_nibbles(transport.raw)
        assert nibbles[:4] == [(0, 0x3), (0, 0x3), (0, 0x3), (0, 0x2)]
        commands = decode_bytes(transport.raw[_MODE_FORCE_WRITES:])
        assert commands == [
            (0, 0x28), (0, 0x08), (0, 0x01), (0, 0x06), (0, 0x0C)]

    def test_init_honors_the_datasheet_timings(self) -> None:
        """The power-on settle, the three mode-force waits, and the clear delay reach the clock in order."""
        _lcd, _transport, sleeps = make_lcd()
        assert sleeps == [50, 5, 1, 1, 2]

    def test_backlight_defaults_on_in_every_byte(self) -> None:
        """Every init byte carries the backlight bit."""
        _lcd, transport, _sleeps = make_lcd()
        raw = transport.raw
        for byte_index in range(len(raw)):
            assert raw[byte_index] & BACKLIGHT

    def test_geometry_outside_the_controller_is_refused(self) -> None:
        """The HD44780 addresses at most 40 columns and 4 rows."""
        with raises(ValueError, match="rows"):
            make_lcd(rows=5)
        with raises(ValueError, match="columns"):
            make_lcd(columns=41)
        with raises(ValueError, match="columns"):
            make_lcd(columns=0)


class TestWrite:
    def test_write_positions_then_sends_text(self) -> None:
        """write() sets the DDRAM address, then sends the characters."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.write("Hi", row=1, column=3)
        assert decode_bytes(transport.raw) == [
            (0, 0x80 | 0x40 + 3),
            (REGISTER_SELECT, ord("H")),
            (REGISTER_SELECT, ord("i"))]

    def test_text_is_clipped_to_the_row_not_wrapped(self) -> None:
        """Characters past the row's end are dropped, and 16 minus column 10 leaves 6."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.write("X" * 30, column=10)
        data = [value for select, value in decode_bytes(transport.raw)
                if select]
        assert len(data) == 6

    def test_exact_fit_and_empty_text_send_only_what_is_there(self) -> None:
        """A row-long string fills the row; an empty one sends the address alone."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.write("0123456789ABCDEF")
        assert len(decode_bytes(transport.raw)) == 17
        del transport.raw[:]
        lcd.write("")
        assert decode_bytes(transport.raw) == [(0, 0x80)]

    def test_out_of_range_position_raises(self) -> None:
        """A row or column outside the panel geometry is refused."""
        lcd, _transport, _sleeps = make_lcd()
        with raises(ValueError):
            lcd.write("x", row=2)
        with raises(ValueError):
            lcd.write("x", column=16)

    def test_a_character_beyond_the_8bit_set_is_refused(self) -> None:
        """The controller's ROM is 8-bit; a wider code point raises instead of truncating."""
        lcd, _transport, _sleeps = make_lcd()
        with raises(ValueError, match="8-bit"):
            lcd.write("20° €")

    def test_four_row_geometry_addresses_the_lower_rows(self) -> None:
        """Rows 2 and 3 continue lines 0 and 1 after ``columns`` cells, on 20 and 16 columns alike."""
        lcd, transport, _sleeps = make_lcd(columns=20, rows=4)
        del transport.raw[:]
        lcd.write("x", row=2)
        assert decode_bytes(transport.raw)[0] == (0, 0x80 | 0x14)
        lcd, transport, _sleeps = make_lcd(columns=16, rows=4)
        del transport.raw[:]
        lcd.write("x", row=2)
        assert decode_bytes(transport.raw)[0] == (0, 0x80 | 0x10)
        del transport.raw[:]
        lcd.write("x", row=3)
        assert decode_bytes(transport.raw)[0] == (0, 0x80 | 0x50)


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
            assert not raw[byte_index] & BACKLIGHT

    def test_toggle_writes_immediately_without_latching(self) -> None:
        """A toggle lands as one data-less write and never strobes enable."""
        lcd, transport, _sleeps = make_lcd()
        del transport.raw[:]
        lcd.backlight = False
        lcd.backlight = True
        assert transport.raw == [0x00, BACKLIGHT]


class FakeLockingI2c:
    """The four-method surface of ``busio.I2C`` the CP transport uses.

    ``refusals`` is how many ``try_lock()`` calls report the bus busy
    before one grants it, so the transport's spin is exercised.
    """

    def __init__(self, refusals: int = 0) -> None:
        self.refusals = refusals
        self.writes: list = []
        self.locked = False
        self.lock_count = 0
        self.unlock_count = 0

    def try_lock(self) -> bool:
        self.lock_count += 1
        if self.refusals:
            self.refusals -= 1
            return False
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

    def test_a_busy_bus_is_retried_until_the_lock_is_granted(self) -> None:
        """Two refusals cost two extra try_lock calls and change nothing else."""
        bus = FakeLockingI2c(refusals=2)
        CircuitPythonTransport(bus).write_byte(0xA5)
        assert bus.writes == [(0x27, b"\xa5")]
        assert bus.lock_count == 3
        assert bus.unlock_count == 1
        assert not bus.locked


class TestMicroPythonTransport:
    def test_writes_one_byte_to_the_backpack_address(self) -> None:
        """One write_byte lands one byte at the default address."""
        bus = FakeMachineI2c()
        MicroPythonTransport(bus).write_byte(0x5A)
        assert bus.writes == [(0x27, b"\x5a")]

    def test_alternate_address_is_used(self) -> None:
        """The A-suffix backpack address reaches every write."""
        bus = FakeMachineI2c()
        transport = MicroPythonTransport(bus, address=0x3F)
        transport.write_byte(1)
        assert bus.writes == [(0x3F, b"\x01")]


def test_default_clock_construction() -> None:
    """Without sleep_ms=, construction waits out the real 59 ms and still configures the panel."""
    transport = RecordingTransport()
    lcd = CharLcd(transport)
    assert lcd.backlight is True
    assert decode_bytes(transport.raw[_MODE_FORCE_WRITES:]) == [
        (0, 0x28), (0, 0x08), (0, 0x01), (0, 0x06), (0, 0x0C)]
