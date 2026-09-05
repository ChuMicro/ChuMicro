"""GC9A01A drivers: a 240x240 round color TFT as chumicro-screens panels.

Two panel classes share the bus protocol and initialization sequence
and differ in what ``frame`` is:

- ``GC9A01AIndexed`` is the portable canvas.  ``frame`` speaks
  framebuf's method vocabulary with palette indexes as colors on both
  device runtimes, and ``set_color(index, red, green, blue)`` is the
  only color entry.  On MicroPython the frame is an 8-bit
  ``framebuf.FrameBuffer`` (57,600 bytes) expanded through the palette
  one strip at a time with ``FrameBuffer.blit``; on CircuitPython it is
  a 16-bit ``displayio.Bitmap`` (115,200 bytes) drawn through
  ``bitmaptools`` with the palette applied as each primitive is drawn.
- ``GC9A01A`` draws at 16-bit depth with raw ``color565`` values, a
  runtime-native extra outside the portable vocabulary: ``frame`` is a
  ``framebuf.FrameBuffer`` on MicroPython and a ``displayio.Bitmap``
  on CircuitPython, both 115,200 bytes.

Either way ``flush()`` is the ScreenService panel protocol: each
advance sends one strip of ``transfer_rows`` rows as a self-contained
transfer (window, then memory write) straight from the frame's buffer,
so a full frame spreads across ticks instead of blocking one.  On
CircuitPython that bypasses displayio's refresh pipeline, whose cost
grows with the dirty area; the bus is the only cost here.

Construction blocks 330 to 365 ms, depending on the board, while the
panel resets and runs its initialization sequence.
"""

import array
import gc
import time

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

try:
    import framebuf
except ImportError:
    framebuf = None

try:
    from time import sleep_ms as _sleep_ms
except ImportError:
    def _sleep_ms(duration_ms: int) -> None:
        """Millisecond sleep for runtimes without ``time.sleep_ms``."""
        time.sleep(duration_ms / 1000)

WIDTH = const(240)
HEIGHT = const(240)

_ROW_BYTES = const(WIDTH * 2)
_PALETTE_SIZE = const(256)
_COLUMN_ADDRESS_COMMAND = b"\x2a"
_ROW_ADDRESS_COMMAND = b"\x2b"
_MEMORY_WRITE_COMMAND = b"\x2c"
_FULL_WIDTH_WINDOW = b"\x00\x00\x00\xef"

_INIT_SEQUENCE = (
    b"\xfe\x00"
    b"\xef\x00"
    b"\xb6\x02\x00\x00"
    b"\x36\x01\x48"
    b"\x3a\x01\x05"
    b"\xc3\x01\x13"
    b"\xc4\x01\x13"
    b"\xc9\x01\x22"
    b"\xf0\x06\x45\x09\x08\x08\x26\x2a"
    b"\xf1\x06\x43\x70\x72\x36\x37\x6f"
    b"\xf2\x06\x45\x09\x08\x08\x26\x2a"
    b"\xf3\x06\x43\x70\x72\x36\x37\x6f"
    b"\x66\x0a\x3c\x00\xcd\x67\x45\x45\x10\x00\x00\x00"
    b"\x67\x0a\x00\x3c\x00\x00\x00\x01\x54\x10\x32\x98"
    b"\x74\x07\x10\x85\x80\x00\x00\x4e\x00"
    b"\x98\x02\x3e\x07"
    b"\x35\x00"
    b"\x21\x00"
    b"\x11\x80\x78"
    b"\x29\x80\x14"
)


def color565(red: int, green: int, blue: int) -> int:
    """Pack 8-bit red, green, blue into the value ``GC9A01A.frame`` drawing takes.

    The value is RGB565 in the panel's on-wire byte order.  Both frame
    backends store 16-bit pixels low byte first while the panel reads
    high byte first, so the helper pre-swaps; a raw RGB565 literal like
    ``0xF800`` renders the wrong color.

    Args:
        red: Red channel, 0 to 255.
        green: Green channel, 0 to 255.
        blue: Blue channel, 0 to 255.

    Returns:
        The 16-bit value to pass to ``frame`` drawing methods.
    """
    value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
    return ((value & 0xFF) << 8) | (value >> 8)


def _reset_panel(reset: object, sleep_ms: object) -> None:
    """Pulse the reset line low, then hold high through panel wake-up."""
    reset(1)
    sleep_ms(5)
    reset(0)
    sleep_ms(20)
    reset(1)
    sleep_ms(150)


def _run_init(spi: object, chip_select: object, data_command: object,
              sleep_ms: object) -> None:
    """Walk the initialization sequence, honoring its embedded delays."""
    sequence = _INIT_SEQUENCE
    index = 0
    while index < len(sequence):
        command_byte = sequence[index]
        control = sequence[index + 1]
        count = control & 0x7F
        _write_command(spi, chip_select, data_command, command_byte,
                       sequence[index + 2:index + 2 + count])
        index += 2 + count
        if control & 0x80:
            sleep_ms(sequence[index])
            index += 1


def _write_command(spi: object, chip_select: object, data_command: object,
                   command_byte: int, data: bytes) -> None:
    """Send one command with its data bytes; init path only, allocates."""
    chip_select(0)
    data_command(0)
    spi.write(bytes((command_byte,)))
    if data:
        data_command(1)
        spi.write(data)
    chip_select(1)


def _bring_up(spi: object, chip_select: object, data_command: object,
              reset: object, sleep_ms: object, locking: bool) -> None:
    """Reset and initialize the panel, holding a ``busio`` lock throughout."""
    if locking:
        while not spi.try_lock():
            pass
    try:
        _reset_panel(reset, sleep_ms)
        _run_init(spi, chip_select, data_command, sleep_ms)
    finally:
        if locking:
            spi.unlock()


def _write_strip(spi: object, chip_select: object, data_command: object,
                 row_window: bytes, strip_view: memoryview,
                 locking: bool) -> None:
    """One self-contained transfer: window commands, then pixel data.

    ``locking`` takes and releases a ``busio.SPI`` lock around the
    transfer, which is how CircuitPython shares a bus; ``machine.SPI``
    has no lock and gets none.
    """
    if locking:
        while not spi.try_lock():
            pass
    try:
        chip_select(0)
        data_command(0)
        spi.write(_COLUMN_ADDRESS_COMMAND)
        data_command(1)
        spi.write(_FULL_WIDTH_WINDOW)
        data_command(0)
        spi.write(_ROW_ADDRESS_COMMAND)
        data_command(1)
        spi.write(row_window)
        data_command(0)
        spi.write(_MEMORY_WRITE_COMMAND)
        data_command(1)
        spi.write(strip_view)
        chip_select(1)
    finally:
        if locking:
            spi.unlock()


def _strip_bounds(transfer_rows: int) -> list:
    """Split 240 rows into ``(row_start, row_count, window)`` strips."""
    strips = []
    row_start = 0
    while row_start < HEIGHT:
        row_count = transfer_rows
        if row_start + row_count > HEIGHT:
            row_count = HEIGHT - row_start
        row_end = row_start + row_count - 1
        window = bytes((row_start >> 8, row_start & 0xFF,
                        row_end >> 8, row_end & 0xFF))
        strips.append((row_start, row_count, window))
        row_start += row_count
    return strips


def _rgb565_bitmap() -> object:
    """Allocate the CircuitPython 16-bit frame; the largest block an app asks for."""
    import displayio
    gc.collect()
    return displayio.Bitmap(WIDTH, HEIGHT, 65536)


def _frame_strips(view: memoryview, transfer_rows: int) -> list:
    """Pre-slice one view per strip so an advance allocates nothing.

    ``view`` may count bytes or 16-bit items, depending on the buffer
    behind it, so a row's length in items is measured rather than assumed.
    """
    items_per_row = len(view) // HEIGHT
    return [
        (row_start, window, view[row_start * items_per_row:
                                 (row_start + row_count) * items_per_row])
        for row_start, row_count, window in _strip_bounds(transfer_rows)]


class GC9A01A:
    """Round TFT panel drawn in raw 16-bit color; flush through ScreenService.

    The bus objects are injected: the app constructs the SPI bus and
    the three control pins and passes them in, so the driver never
    imports ``machine`` or ``busio``.  Pins follow the callable protocol
    (``pin(1)`` drives high); the SPI object needs ``write``, plus
    ``try_lock`` and ``unlock`` when it is a ``busio.SPI``.

    ``frame`` stores pixels in the panel's on-wire byte order, so
    colors come from ``color565``, never from raw RGB565 literals.  On
    MicroPython it is a ``framebuf.FrameBuffer`` with framebuf's
    drawing methods; on CircuitPython it is a ``displayio.Bitmap`` for
    ``bitmaptools`` to draw on.  Either way the frame is 115,200 bytes,
    so this class wants a PSRAM-class board on MicroPython and leaves a
    Pi Pico W about 43 KB under CircuitPython once the driver's own code
    is loaded; the portable ``GC9A01AIndexed`` is the smaller shape on
    MicroPython.

    ``transfer_rows`` bounds one flush advance.  Sizing datum from the
    LOLIN S2 Mini bench at 40 MHz SPI: a 10-row strip averages 3.3 ms
    with a worst case under 4 ms, inside a 5 ms tick, and a full frame
    crosses in 24 advances, about 80 ms.  A Pi Pico W under
    CircuitPython streams a 10-row strip in about 2.1 ms mean and
    2.5 ms worst, 53 ms a frame.

    Args:
        spi: SPI bus wired to the panel, clock and data lines.
        chip_select: Output pin on the panel's CS line.
        data_command: Output pin on the panel's DC line.
        reset: Output pin on the panel's RST line.
        transfer_rows: Rows sent per flush advance, 1 to 240.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, spi: object, chip_select: object, data_command: object,
                 reset: object, *, transfer_rows: int = 10,
                 sleep_ms: object | None = None) -> None:
        if not 1 <= transfer_rows <= HEIGHT:
            raise ValueError("transfer_rows must be 1 to 240")
        self._spi = spi
        self._chip_select = chip_select
        self._data_command = data_command
        self._locking = hasattr(spi, "try_lock")
        self.width = WIDTH
        self.height = HEIGHT
        if framebuf is None:
            self.frame = _rgb565_bitmap()
            view = memoryview(self.frame)
        else:
            # The frame needs one contiguous block, so reclaim the compile
            # scratch the import chain left interleaved with live objects.
            gc.collect()
            self._buffer = bytearray(WIDTH * HEIGHT * 2)
            view = memoryview(self._buffer)
            self.frame = framebuf.FrameBuffer(self._buffer, WIDTH, HEIGHT,
                                              framebuf.RGB565)
        self._strips = _frame_strips(view, transfer_rows)
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        _bring_up(spi, chip_select, data_command, reset, sleep_ms, self._locking)

    def flush(self) -> object:
        """Send the frame one strip per advance; the panel protocol."""
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        locking = self._locking
        first = True
        for _row_start, window, view in self._strips:
            if not first:
                yield
            first = False
            _write_strip(spi, chip_select, data_command, window, view, locking)


class GC9A01AIndexed:
    """Round TFT panel as the portable canvas: palette indexes, one API on both runtimes.

    Drawing on ``frame`` uses palette indexes as colors: assign an index
    a color with ``set_color``, then draw with the index.  Index 0
    starts black.  ``frame`` offers framebuf's method vocabulary on
    both runtimes: ``fill``, ``pixel``, ``hline``, ``vline``, ``line``,
    ``rect``, ``fill_rect``, ``ellipse``, ``poly``, ``blit``, ``text``.
    On MicroPython it is the ``framebuf.FrameBuffer`` itself; on
    CircuitPython it is a canvas over a 16-bit ``displayio.Bitmap``
    that draws circles rather than general ellipses, polygon outlines
    rather than fills, and the runtime's own font, whose metrics differ
    from framebuf's 8x8.

    RAM differs by runtime.  MicroPython holds the frame at one byte per
    pixel (57,600 bytes) plus a 256-entry palette, about half the RAM
    of ``GC9A01A``, so a Pico W heap fits it, and each flush advance
    expands one strip through the palette with ``FrameBuffer.blit`` at
    C speed.  CircuitPython holds 16-bit pixels (115,200 bytes) because
    its firmware offers no C-speed palette expansion outside displayio;
    a Pi Pico W's larger CircuitPython heap holds it with about 43 KB to
    spare, driver code included, when the panel is constructed first.  A ``set_color`` after
    drawing recolors the drawn pixels on MicroPython from the next flush
    on; on CircuitPython it applies to later drawing only.

    Construct early: the frame needs one contiguous block, which a
    fragmented heap may no longer hold.

    ``transfer_rows`` defaults for the 256 KB class.  Sizing datum from
    the Pi Pico W bench under MicroPython, where ``machine.SPI`` clamps
    a 40 MHz request to 24 MHz: the default 6-row strip measured 3.6 ms
    at worst, inside a 5 ms tick, and a full frame crosses in 40
    advances, about 123 ms.  The strip size was fitted with a model of
    0.2 ms fixed plus 0.5 ms per row.  Under CircuitPython the same
    board streams a 6-row strip in 1.4 ms mean and 2.0 ms worst, 62 ms
    a frame, since no palette expansion happens per strip.  Taller
    strips barely shorten the MicroPython frame; a faster chip can
    raise ``transfer_rows`` as its own bench allows.

    Args:
        spi: SPI bus wired to the panel, clock and data lines.
        chip_select: Output pin on the panel's CS line.
        data_command: Output pin on the panel's DC line.
        reset: Output pin on the panel's RST line.
        transfer_rows: Rows sent per flush advance, 1 to 240.  On
            MicroPython each row costs 480 bytes of strip buffer on top
            of the frame.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, spi: object, chip_select: object, data_command: object,
                 reset: object, *, transfer_rows: int = 6,
                 sleep_ms: object | None = None) -> None:
        if not 1 <= transfer_rows <= HEIGHT:
            raise ValueError("transfer_rows must be 1 to 240")
        self._spi = spi
        self._chip_select = chip_select
        self._data_command = data_command
        self._locking = hasattr(spi, "try_lock")
        self.width = WIDTH
        self.height = HEIGHT
        if framebuf is None:
            import bitmaptools
            import displayio
            import terminalio

            from chumicro_screens.bitmap_canvas import BitmapCanvas
            bitmap = _rgb565_bitmap()
            view = memoryview(bitmap)
            glyph_width, glyph_height = terminalio.FONT.get_bounding_box()
            self._colors = array.array("H", bytes(_PALETTE_SIZE * 2))
            self._palette_frame = None
            self._strip_frame = None
            self.frame = BitmapCanvas(
                bitmap, self._colors, bitmaptools, terminalio.FONT,
                displayio.Bitmap(glyph_width, glyph_height, 65536))
            self._strips = _frame_strips(view, transfer_rows)
        else:
            # The frame needs one contiguous block, so reclaim the compile
            # scratch the import chain left interleaved with live objects.
            gc.collect()
            self._buffer = bytearray(WIDTH * HEIGHT)
            self.frame = framebuf.FrameBuffer(self._buffer, WIDTH, HEIGHT,
                                              framebuf.GS8)
            strip_buffer = bytearray(transfer_rows * _ROW_BYTES)
            strip_view = memoryview(strip_buffer)
            self._strip_frame = framebuf.FrameBuffer(strip_buffer, WIDTH,
                                                     transfer_rows,
                                                     framebuf.RGB565)
            self._palette_frame = framebuf.FrameBuffer(
                bytearray(_PALETTE_SIZE * 2), _PALETTE_SIZE, 1, framebuf.RGB565)
            self._strips = [
                (row_start, window, strip_view[:row_count * _ROW_BYTES])
                for row_start, row_count, window in _strip_bounds(transfer_rows)]
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        _bring_up(spi, chip_select, data_command, reset, sleep_ms, self._locking)

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        """Assign palette entry ``index`` the given 8-bit channels.

        On MicroPython, drawing ``index`` on ``frame`` renders this color
        from the next flush on and already-drawn pixels holding the
        index change with it.  On CircuitPython the color applies to
        drawing done after the call.

        Args:
            index: Palette slot, 0 to 255.
            red: Red channel, 0 to 255.
            green: Green channel, 0 to 255.
            blue: Blue channel, 0 to 255.
        """
        value = color565(red, green, blue)
        if self._palette_frame is None:
            self._colors[index] = value
        else:
            self._palette_frame.pixel(index, 0, value)

    def flush(self) -> object:
        """Expand and send one strip per advance; the panel protocol."""
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        locking = self._locking
        frame = self.frame
        strip_frame = self._strip_frame
        palette_frame = self._palette_frame
        first = True
        for row_start, window, view in self._strips:
            if not first:
                yield
            first = False
            if strip_frame is not None:
                strip_frame.blit(frame, 0, -row_start, -1, palette_frame)
            _write_strip(spi, chip_select, data_command, window, view, locking)
