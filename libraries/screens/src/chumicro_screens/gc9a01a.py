"""GC9A01A drivers: a 240x240 round color TFT as chumicro-screens panels.

Two panel classes share the bus protocol and initialization sequence
and differ in what ``frame`` is:

- ``GC9A01AIndexed`` is the portable canvas.  ``frame`` speaks
  framebuf's method vocabulary with palette indexes as colors on both
  device runtimes, and ``set_color(index, red, green, blue)`` is the
  only color entry.  The frame holds one byte per pixel (57,600 bytes)
  on both runtimes, and each flush advance expands one strip through
  the palette in C: ``FrameBuffer.blit`` with a palette on MicroPython,
  a raw ``bitmaptools.blit`` plus one ``replace_color`` pass per
  assigned color on CircuitPython.  With ``frame_bits=16`` CircuitPython
  holds a 16-bit ``displayio.Bitmap`` (115,200 bytes) instead, drawn
  with the palette applied as each primitive lands and streamed with no
  expansion.
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


def _frame_bitmap(values: int) -> object:
    """Allocate the CircuitPython frame at ``values`` per pixel; the largest block an app asks for."""
    import displayio
    gc.collect()
    return displayio.Bitmap(WIDTH, HEIGHT, values)


def _expansion_passes(palette: object, assigned: bytearray) -> list:
    """Plan the ``replace_color`` passes that turn a strip of indexes into colors.

    A pass rewrites every pixel holding ``old`` as ``new``, so an index
    whose color is a number below 256 could be mistaken for another
    index by a later pass.  Such indexes first move to a temporary value
    above 255 that no color uses, the other indexes take their colors
    directly, and the temporaries take their colors last, after every
    index value has left the strip.  An index equal to its own color
    needs no pass, which is what index 0 in black is.
    """
    colors = set()
    for index in range(_PALETTE_SIZE):
        if assigned[index]:
            colors.add(palette[index])
    passes = []
    deferred = []
    temporary = _PALETTE_SIZE
    for index in range(_PALETTE_SIZE):
        if not assigned[index]:
            continue
        color = palette[index]
        if color == index:
            continue
        if color >= _PALETTE_SIZE:
            passes.append((index, color))
            continue
        while temporary in colors:
            temporary += 1
        passes.append((index, temporary))
        deferred.append((temporary, color))
        temporary += 1
    passes.extend(deferred)
    return passes


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
            self.frame = _frame_bitmap(65536)
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
    CircuitPython it is a canvas over a ``displayio.Bitmap`` that draws
    circles rather than general ellipses, polygon outlines rather than
    fills, and its ``text`` in the runtime's own built-in font, whose
    metrics differ from framebuf's 8x8.
    ``chumicro_screens.fonts.Font`` draws a converted font at the same
    pixels on both runtimes.

    The frame is one byte per pixel (57,600 bytes) plus a 256-entry
    palette on both runtimes, so a Pi Pico W heap holds it under either,
    and a ``set_color`` after drawing recolors every drawn pixel holding
    that index from the next flush on.  Each flush advance expands one
    strip through the palette in C.  MicroPython does it in one
    ``FrameBuffer.blit``.  CircuitPython copies the strip raw with
    ``bitmaptools.blit`` and runs one ``replace_color`` pass per
    assigned color (two for a color whose pre-swapped value is below
    256, pure red among them), so its advance grows with the palette: on
    a Pi Pico W an advance at the default 3-row strip costs about 2.1 ms
    plus 0.45 ms per pass, 2.5 ms with black and white, 4.4 ms with four
    more colors, 6.1 ms with seven, and a frame about 175 ms plus 35 ms
    per pass, so five passes fit a 5 ms tick at 3 rows and a larger
    palette wants ``transfer_rows=2``.  ``frame_bits=16`` trades RAM for that time on
    CircuitPython: a 16-bit frame (115,200 bytes) holds colors rather
    than indexes, so no expansion runs and a 6-row strip streams in
    1.4 ms mean and 2.0 ms worst, 62 ms a frame, but ``set_color``
    applies to later drawing only, and a Pi Pico W holds the frame with
    about 43 KB to spare only when the panel is constructed before
    anything else.  MicroPython's frame is 8-bit whatever ``frame_bits``
    says.

    Construct early: the frame needs one contiguous block, which a
    fragmented heap may no longer hold.

    ``transfer_rows`` defaults to 6, or 3 on the CircuitPython 8-bit
    frame.  Sizing datum from the Pi Pico W bench under MicroPython,
    where ``machine.SPI`` clamps a 40 MHz request to 24 MHz: the 6-row
    strip measured 3.6 ms at worst, inside a 5 ms tick, and a full frame
    crosses in 40 advances, about 123 ms, fitted with a model of 0.2 ms
    fixed plus 0.5 ms per row, so taller strips barely shorten the
    frame.  A faster chip can raise ``transfer_rows`` as its own bench
    allows.

    Args:
        spi: SPI bus wired to the panel, clock and data lines.
        chip_select: Output pin on the panel's CS line.
        data_command: Output pin on the panel's DC line.
        reset: Output pin on the panel's RST line.
        transfer_rows: Rows sent per flush advance, 1 to 240.  Each row
            costs 480 bytes of strip buffer on top of the frame, and on
            the CircuitPython 8-bit frame each palette pass costs about
            0.15 ms per row per advance.
        frame_bits: 8 or 16, the CircuitPython frame's bits per pixel.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, spi: object, chip_select: object, data_command: object,
                 reset: object, *, transfer_rows: int | None = None,
                 frame_bits: int = 8, sleep_ms: object | None = None) -> None:
        if frame_bits not in (8, 16):
            raise ValueError("frame_bits must be 8 or 16")
        if transfer_rows is None:
            transfer_rows = 3 if framebuf is None and frame_bits == 8 else 6
        if not 1 <= transfer_rows <= HEIGHT:
            raise ValueError("transfer_rows must be 1 to 240")
        self._spi = spi
        self._chip_select = chip_select
        self._data_command = data_command
        self._locking = hasattr(spi, "try_lock")
        self.width = WIDTH
        self.height = HEIGHT
        self._strip = None
        self._assigned = None
        self._passes = None
        if framebuf is None:
            import bitmaptools
            import displayio
            import terminalio

            from chumicro_screens.bitmap_canvas import BitmapCanvas
            self._tools = bitmaptools
            self._palette_frame = None
            self._strip_frame = None
            self._colors = array.array("H", bytes(_PALETTE_SIZE * 2))
            if frame_bits == 16:
                bitmap = _frame_bitmap(65536)
                canvas_colors = self._colors
                self._strips = _frame_strips(memoryview(bitmap), transfer_rows)
            else:
                bitmap = _frame_bitmap(_PALETTE_SIZE)
                canvas_colors = bytes(range(_PALETTE_SIZE))
                self._assigned = bytearray(_PALETTE_SIZE)
                self._assigned[0] = 1
                self._strip = displayio.Bitmap(WIDTH, transfer_rows, 65536)
                strip_view = memoryview(self._strip)
                self._items_per_row = len(strip_view) // transfer_rows
                self._strips = [
                    (row_start, window, strip_view[:row_count * self._items_per_row])
                    for row_start, row_count, window in _strip_bounds(transfer_rows)]
            self._bitmap = bitmap
            self.frame = BitmapCanvas(bitmap, canvas_colors, bitmaptools,
                                      terminalio.FONT, displayio)
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

        Drawing ``index`` on ``frame`` renders this color from the next
        flush on, and already-drawn pixels holding the index change with
        it.  On a 16-bit CircuitPython frame the color applies to
        drawing done after the call instead.

        Args:
            index: Palette slot, 0 to 255.
            red: Red channel, 0 to 255.
            green: Green channel, 0 to 255.
            blue: Blue channel, 0 to 255.
        """
        value = color565(red, green, blue)
        if self._palette_frame is not None:
            self._palette_frame.pixel(index, 0, value)
            return
        self._colors[index] = value
        if self._assigned is not None:
            self._assigned[index] = 1
            self._passes = None

    def flush(self) -> object:
        """Expand and send one strip per advance; the panel protocol."""
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        locking = self._locking
        frame = self.frame
        strip_frame = self._strip_frame
        palette_frame = self._palette_frame
        strip = self._strip
        if strip is not None:
            tools = self._tools
            bitmap = self._bitmap
            items_per_row = self._items_per_row
            passes = self._passes
            if passes is None:
                passes = self._passes = _expansion_passes(self._colors, self._assigned)
        first = True
        for row_start, window, view in self._strips:
            if not first:
                yield
            first = False
            if strip_frame is not None:
                strip_frame.blit(frame, 0, -row_start, -1, palette_frame)
            elif strip is not None:
                tools.blit(strip, bitmap, 0, 0, x1=0, y1=row_start, x2=WIDTH,
                           y2=row_start + len(view) // items_per_row)
                for old, new in passes:
                    tools.replace_color(strip, old, new)
            _write_strip(spi, chip_select, data_command, window, view, locking)
