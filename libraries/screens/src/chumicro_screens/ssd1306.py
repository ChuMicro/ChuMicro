"""SSD1306 monochrome OLED as a chumicro-screens panel, one page per strip.

The controller holds its frame as pages of eight vertically stacked
pixels, one byte per column, which is exactly ``framebuf``'s
``MONO_VLSB`` layout.  The panel's strip is one such page over the
bytes the bus sends, behind the panel's data control byte, so a page
leaves in one ``writeto`` with no copy on either I2C port, and a
``Screen`` paints the panel eight rows at a time with no frame in RAM.

At 400 kHz one page crosses a LOLIN S2 Mini in 3.7 ms mean and 3.9 ms
worst and a Pi Pico W in 3.5 ms and 3.8 ms, inside a 5 ms tick; at
100 kHz a page takes 13 ms, so a panel sharing a tick budget wants
the faster bus.

Pixel values are 0 for dark and 1 for lit.  The panel is emissive and
generates its own drive voltage on an internal charge pump, so it runs
from 3V3 with no contrast rail.  Construction blocks about 100 ms
while the charge pump settles.
"""

__chumicro_runtimes__ = ("micropython",)

import time

from chumicro_screens.framebuf_strip import FramebufStrip

try:
    import framebuf
except ImportError:
    framebuf = None

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

# Co=0, D/C#=1: every byte after this one in the write is pixel data.
_CONTROL_DATA = const(0x40)
# Co=0, D/C#=0: every byte after this one in the write is a command.
_CONTROL_COMMAND = const(0x00)

_SET_MEMORY_MODE = const(0x20)
_SET_COLUMN_ADDRESS = const(0x21)
_SET_PAGE_ADDRESS = const(0x22)
_SET_START_LINE = const(0x40)
_SET_CONTRAST = const(0x81)
_SET_CHARGE_PUMP = const(0x8D)
_SET_SEGMENT_REMAP = const(0xA1)
_RESUME_FROM_RAM = const(0xA4)
_SET_NORMAL_DISPLAY = const(0xA6)
_SET_MULTIPLEX_RATIO = const(0xA8)
_DISPLAY_OFF = const(0xAE)
_DISPLAY_ON = const(0xAF)
_SET_COM_SCAN_DECREMENT = const(0xC8)
_SET_DISPLAY_OFFSET = const(0xD3)
_SET_DISPLAY_CLOCK = const(0xD5)
_SET_PRECHARGE = const(0xD9)
_SET_COM_PIN_CONFIG = const(0xDA)
_SET_VCOM_DESELECT = const(0xDB)

_PAGE_HEIGHT = const(8)


def _init_sequence(height: int) -> bytes:
    """Build the power-on command sequence for one panel height.

    Multiplex ratio is the row count less one, and the COM pin
    configuration selects sequential or alternating pins, which is the
    one place a 32-row panel differs from a 64-row one.  Start line,
    display offset, and resume-from-RAM restate the power-on defaults
    so a warm MCU reboot against a scrolled or test-patterned panel
    lands in a known state.
    """
    com_pins = 0x02 if height == 32 else 0x12
    return bytes((
        _DISPLAY_OFF,
        _SET_MEMORY_MODE, 0x00,          # horizontal, so a window auto-advances
        _SET_START_LINE | 0x00,
        _SET_SEGMENT_REMAP,              # column 0 maps to segment 127
        _SET_COM_SCAN_DECREMENT,         # scan rows bottom to top
        _SET_MULTIPLEX_RATIO, height - 1,
        _SET_DISPLAY_OFFSET, 0x00,
        _SET_COM_PIN_CONFIG, com_pins,
        _SET_DISPLAY_CLOCK, 0x80,        # default divide, ~370 kHz oscillator
        _SET_PRECHARGE, 0xF1,            # internal charge pump timing
        _SET_VCOM_DESELECT, 0x30,        # 0.83 x VCC, the same on both runtimes
        _SET_CONTRAST, 0xFF,
        _RESUME_FROM_RAM,                # show RAM, not an all-on test pattern
        _SET_NORMAL_DISPLAY,
        _SET_CHARGE_PUMP, 0x14,          # enable the internal DC/DC
        _DISPLAY_ON,
    ))


class SSD1306:
    """Monochrome OLED panel for a ``Screen``: one page of eight rows per strip.

    The bus is injected: the app constructs the I2C bus and passes it
    in, so the driver never imports ``machine``.  The bus needs only
    ``writeto``.

    Args:
        i2c: I2C bus wired to the panel.
        address: The panel's I2C address; 0x3C by default, 0x3D when
            the module's address jumper is bridged.
        width: Panel width in pixels.
        height: Panel height in pixels; a multiple of 8.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, i2c: object, address: int = 0x3C, *,
                 width: int = 128, height: int = 64,
                 sleep_ms: object | None = None) -> None:
        if height % _PAGE_HEIGHT:
            raise ValueError(f"height {height} is not a multiple of 8")
        if sleep_ms is None:
            sleep_ms = time.sleep_ms
        self._i2c = i2c
        self._address = address
        self._sleep_ms = sleep_ms
        self.width = width
        self.height = height
        # The control byte ahead of the page's bytes, so the page leaves
        # the buffer as a single write.
        self._buffer = bytearray(1 + width)
        self._buffer[0] = _CONTROL_DATA
        self.strip = FramebufStrip(memoryview(self._buffer)[1:], width, _PAGE_HEIGHT,
                                   framebuf.MONO_VLSB)
        # One address window per page, columns and page in a single
        # write, so each transfer is self-contained and a dropped frame
        # leaves no half-set window behind.
        self._page_windows = []
        page = 0
        while page < height // _PAGE_HEIGHT:
            self._page_windows.append(bytes((
                _CONTROL_COMMAND,
                _SET_COLUMN_ADDRESS, 0, width - 1,
                _SET_PAGE_ADDRESS, page, page,
            )))
            page += 1
        self._command_buffer = bytearray(2)
        self._command_buffer[0] = _CONTROL_COMMAND
        self._run_init()

    def _run_init(self) -> None:
        """Walk the power-on sequence and wait for the charge pump."""
        self._i2c.writeto(self._address,
                          bytes((_CONTROL_COMMAND,))
                          + _init_sequence(self.height))
        self._sleep_ms(100)

    def set_contrast(self, value: int) -> None:
        """Set the panel's drive current, 0 to 255.

        This is brightness on an emissive panel, not the bias voltage
        a character LCD's contrast pot trims.

        Args:
            value: Contrast level, 0 (dimmest) to 255 (brightest).
        """
        if not 0 <= value <= 255:
            raise ValueError(f"contrast {value} outside 0..255")
        self._command_buffer[1] = _SET_CONTRAST
        self._i2c.writeto(self._address, self._command_buffer)
        self._command_buffer[1] = value
        self._i2c.writeto(self._address, self._command_buffer)

    def write_strip(self, top: int, count: int, left: int, right: int) -> None:
        """Send the strip as the whole page holding panel row ``top``; the ``Screen`` panel protocol.

        The page always goes in full: its bytes follow the control byte
        in one buffer, so a column window would cost a copy per page.

        Args:
            top: Panel row the strip's row 0 holds, a multiple of 8.
            count: Rows to send, always the full page here.
            left: First dirty column, not used.
            right: One past the last dirty column, not used.
        """
        self._i2c.writeto(self._address, self._page_windows[top // _PAGE_HEIGHT])
        self._i2c.writeto(self._address, self._buffer)
