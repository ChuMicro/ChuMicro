"""SSD1306 monochrome OLED as a chumicro-screens panel.

The controller holds its frame as pages of eight vertically stacked
pixels, one byte per column, which is exactly ``framebuf``'s
``MONO_VLSB`` layout.  ``frame`` therefore draws straight into the
bytes the panel reads, with no conversion pass at flush time.  The
buffer carries the panel's data control byte ahead of every page row,
so a page and its prefix leave in one ``writeto`` with no copy on
either I2C port.

``flush()`` is the ScreenService panel protocol: each advance sends
``transfer_pages`` pages as a self-contained transfer (address window,
then one write per page), so a full frame spreads across ticks instead
of blocking one, and only the page groups covering the rows drawn
since the last flush go at all, so a counter redrawing one line of
text sends one or two pages rather than eight.  The stock drivers push
the whole buffer in a single blocking write, which a cooperative loop
cannot afford.

Drawing is one bit per pixel: 0 is dark, 1 is lit.  The panel is
emissive and generates its own drive voltage on an internal charge
pump, so it runs from 3V3 with no contrast rail.

Construction blocks about 100 ms while the charge pump settles.
"""

__chumicro_runtimes__ = ("micropython",)

import time

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


def _page_windows(width: int, pages: int, transfer_pages: int) -> list:
    """Split the frame into ``(command_bytes, first_page, page_count)`` groups.

    The command bytes address one group's column span and page span in
    a single write, so each flush advance is self-contained and a
    dropped frame leaves no half-set window behind.
    """
    windows = []
    first_page = 0
    while first_page < pages:
        page_count = transfer_pages
        if first_page + page_count > pages:
            page_count = pages - first_page
        last_page = first_page + page_count - 1
        commands = bytes((
            _CONTROL_COMMAND,
            _SET_COLUMN_ADDRESS, 0, width - 1,
            _SET_PAGE_ADDRESS, first_page, last_page,
        ))
        windows.append((commands, first_page, page_count))
        first_page += page_count
    return windows


class SSD1306:
    """Monochrome OLED panel: draw on ``frame``, flush through ScreenService.

    The bus is injected: the app constructs the I2C bus and passes it
    in, so the driver never imports ``machine``.  The bus needs only
    ``writeto``.

    ``frame`` is a ``chumicro_screens.framebuf_canvas.FramebufCanvas``
    in ``MONO_VLSB``, so every framebuf drawing method applies, colors
    are 0 or 1, ``chumicro_screens.fonts.Font`` draws on it, and the
    rows each primitive touched decide which pages the next flush
    sends.  A new panel sends its whole frame on the first flush.

    ``transfer_pages`` bounds one flush advance.  Sizing data from the
    LOLIN S2 Mini bench, 128x64 panel: at 400 kHz one page averages
    3.7 ms with a worst case of 3.9 ms, inside a 5 ms tick, and a full
    frame crosses in 8 advances.  Every larger setting leaves the
    budget, four pages costing 12.6 ms, and so does one page at
    100 kHz, at 13.0 ms.  A Pi Pico W measures one page at 3.5 ms mean
    and 3.8 ms worst.  A panel sharing a tick budget therefore wants a
    400 kHz bus and the default; the knob serves callers pacing the
    flush themselves.

    Args:
        i2c: I2C bus wired to the panel.
        address: The panel's I2C address; 0x3C by default, 0x3D when
            the module's address jumper is bridged.
        width: Panel width in pixels.
        height: Panel height in pixels; a multiple of 8.
        transfer_pages: Pages sent per flush advance, 1 to the panel's
            page count.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, i2c: object, address: int = 0x3C, *,
                 width: int = 128, height: int = 64,
                 transfer_pages: int = 1,
                 sleep_ms: object | None = None) -> None:
        if height % _PAGE_HEIGHT:
            raise ValueError(f"height {height} is not a multiple of 8")
        pages = height // _PAGE_HEIGHT
        if not 1 <= transfer_pages <= pages:
            raise ValueError(f"transfer_pages must be 1 to {pages}")
        if sleep_ms is None:
            sleep_ms = time.sleep_ms
        self._i2c = i2c
        self._address = address
        self._sleep_ms = sleep_ms
        self.width = width
        self.height = height
        self.pages = pages
        # One control byte ahead of every page row, so a page leaves the
        # buffer as a single write; framebuf reads the rows at a stride
        # one wider than the panel to step over the prefixes.
        row_stride = width + 1
        self._buffer = bytearray(pages * row_stride)
        page = 0
        while page < pages:
            self._buffer[page * row_stride] = _CONTROL_DATA
            page += 1
        buffer_view = memoryview(self._buffer)
        import framebuf

        from chumicro_screens.framebuf_canvas import FramebufCanvas
        self.frame = FramebufCanvas(buffer_view[1:], width, height,
                                    framebuf.MONO_VLSB, row_stride)
        self._windows = []
        for commands, first_page, page_count in _page_windows(
                width, pages, transfer_pages):
            views = []
            page = first_page
            while page < first_page + page_count:
                start = page * row_stride
                views.append(buffer_view[start:start + row_stride])
                page += 1
            self._windows.append((commands, tuple(views)))
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

    def flush(self) -> object:
        """Send the page groups covering the drawn rows, one group per advance; the panel protocol."""
        x1, y1, x2, y2 = self.frame.take_dirty()
        if x1 >= x2:
            return
        i2c = self._i2c
        address = self._address
        windows = self._windows
        pages_per_group = len(windows[0][1])
        index = y1 // _PAGE_HEIGHT // pages_per_group
        last = (y2 - 1) // _PAGE_HEIGHT // pages_per_group
        first = True
        while index <= last:
            if not first:
                yield
            first = False
            commands, views = windows[index]
            index += 1
            i2c.writeto(address, commands)
            for view in views:
                i2c.writeto(address, view)
