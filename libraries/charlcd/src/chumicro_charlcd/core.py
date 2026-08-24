"""HD44780 character LCD behind a PCF8574 I2C backpack.

``CharLcd`` speaks the HD44780 protocol against a one-method transport
seam, so the core never imports a bus API and runs on every runtime.
``CircuitPythonTransport`` and ``MicropythonTransport`` are the two
shipped seam implementations; both take an already-constructed I2C
bus, so the library imports no hardware modules at all.

Backpack bit map, the common LCM1602 IIC pinout::

    P0 = RS    P1 = RW    P2 = E    P3 = backlight    P4-P7 = D4-D7

The panel runs in 4-bit mode: each byte goes out as two nibbles, each
nibble as two bus writes (enable high, then low).  The busy flag is
never read; timed waits are simpler, universal, and the datasheet
numbers are generous.

Construction blocks about 60 ms for the panel's power-on settle and
mode-forcing sequence.
"""

import time

_REGISTER_SELECT = 0x01
_ENABLE = 0x04
_BACKLIGHT = 0x08

# DDRAM base address per row.  Two entries serve a 16x2; the last two
# make the same class drive a 20x4 unmodified.
_ROW_ADDRESSES = (0x00, 0x40, 0x14, 0x54)


def _sleep_ms(duration_ms: int) -> None:
    """Sleep via ``time.sleep_ms`` when present, otherwise ``time.sleep``."""
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if runtime_sleep_ms is not None:
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


class CharLcd:
    """HD44780 protocol against a byte-write transport.

    Args:
        transport: Object with ``write_byte(value)`` putting one raw
            byte on the PCF8574.  ``CircuitPythonTransport`` or
            ``MicropythonTransport`` on a device; tests inject
            ``chumicro_charlcd.testing.RecordingTransport``.
        columns: Panel width in character cells.
        rows: Panel height in rows.  Text is clipped to the row, not
            wrapped: HD44780 wrapping lands mid-line on the other row
            and never reads as intended.
        sleep_ms: Millisecond-sleep callable used for the controller's
            timed waits.  Defaults to the real clock; tests inject a
            recorder so nothing actually waits.
    """

    def __init__(self, transport: object, *, columns: int = 16, rows: int = 2,
                 sleep_ms: object | None = None) -> None:
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        self._transport = transport
        self._sleep_ms = sleep_ms
        self.columns = columns
        self.rows = rows
        self._backlight = _BACKLIGHT
        self._initialize_panel()

    def _initialize_panel(self) -> None:
        """Force the controller to a known state, then configure it.

        Three 8-bit "function set" nibbles land the controller in a
        known mode from any starting state (fresh power-up, a reset
        that interrupted a 4-bit pair, a warm MCU reboot against a
        still-configured panel); one more drops it to 4-bit mode.
        """
        self._sleep_ms(50)              # power-on settle
        for wait_ms in (5, 1, 1):       # >=4.1 ms, >=100 us, >=100 us
            self._write_nibble(0x03, 0)
            self._sleep_ms(wait_ms)
        self._write_nibble(0x02, 0)     # 4-bit from here on
        self._command(0x28)             # function set: 4-bit, 2 lines, 5x8
        self._command(0x08)             # display off while configuring
        self.clear()
        self._command(0x06)             # entry mode: cursor advances
        self._command(0x0C)             # display on, cursor hidden

    def clear(self) -> None:
        """Blank the panel and home the cursor."""
        self._command(0x01)
        self._sleep_ms(2)               # the one genuinely slow command

    def write(self, text: str, *, row: int = 0, column: int = 0) -> None:
        """Write ``text`` starting at (``row``, ``column``), clipped to the row.

        Args:
            text: Characters to draw; anything past the row's end is
                dropped.
            row: Target row, 0-based.
            column: Starting cell in the row, 0-based.
        """
        if not 0 <= row < self.rows:
            raise ValueError(f"row {row} outside 0..{self.rows - 1}")
        if not 0 <= column < self.columns:
            raise ValueError(f"column {column} outside 0..{self.columns - 1}")
        self._command(0x80 | (_ROW_ADDRESSES[row] + column))
        for character in text[:self.columns - column]:
            self._send(ord(character), _REGISTER_SELECT)

    @property
    def backlight(self) -> bool:
        """Backlight state; assignable.  The bit rides in every bus byte."""
        return bool(self._backlight)

    @backlight.setter
    def backlight(self, on: bool) -> None:
        self._backlight = _BACKLIGHT if on else 0
        # A data-less write (enable low, nothing latched) so the change
        # lands now rather than at the next text update.
        self._transport.write_byte(self._backlight)

    def _command(self, value: int) -> None:
        self._send(value, 0)

    def _send(self, value: int, register_select: int) -> None:
        self._write_nibble(value >> 4, register_select)
        self._write_nibble(value & 0x0F, register_select)

    def _write_nibble(self, nibble: int, register_select: int) -> None:
        byte = (nibble << 4) | self._backlight | register_select
        self._transport.write_byte(byte | _ENABLE)
        self._transport.write_byte(byte)


class CircuitPythonTransport:
    """PCF8574 byte writes on a ``busio.I2C`` bus.

    Locks around every byte so display traffic interleaves politely
    with sensors on a shared bus; at human update rates the lock
    churn is invisible.

    Args:
        i2c: A constructed ``busio.I2C`` bus.
        address: The backpack's I2C address; solder jumpers select
            0x27 (default) down to 0x20, and A-suffix parts use 0x3F.
    """

    def __init__(self, i2c: object, address: int = 0x27) -> None:
        self._i2c = i2c
        self._address = address
        self._buffer = bytearray(1)

    def write_byte(self, value: int) -> None:
        """Put one raw byte on the backpack, locking around the write."""
        self._buffer[0] = value
        i2c = self._i2c
        while not i2c.try_lock():
            pass
        try:
            i2c.writeto(self._address, self._buffer)
        finally:
            i2c.unlock()


class MicropythonTransport:
    """PCF8574 byte writes on a ``machine.I2C`` bus.

    Args:
        i2c: A constructed ``machine.I2C`` bus.
        address: The backpack's I2C address; solder jumpers select
            0x27 (default) down to 0x20, and A-suffix parts use 0x3F.
    """

    def __init__(self, i2c: object, address: int = 0x27) -> None:
        self._i2c = i2c
        self._address = address
        self._buffer = bytearray(1)

    def write_byte(self, value: int) -> None:
        """Put one raw byte on the backpack."""
        self._buffer[0] = value
        self._i2c.writeto(self._address, self._buffer)
