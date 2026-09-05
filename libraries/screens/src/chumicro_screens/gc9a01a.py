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
so a full frame spreads across ticks instead of blocking one.  The
portable canvas records what was drawn, and ``GC9A01AIndexed``'s
flush sends only the strips covering that rectangle, windowed to its
columns, so a redraw of a few digits costs a few advances rather than
a frame.  On CircuitPython that bypasses displayio's refresh pipeline,
whose cost grows with the dirty area; the bus is the only cost here.

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
else:
    # Loaded with the driver rather than at construction, so the
    # canvas class's objects sit with the import-time code instead of
    # splitting the free region the frame is about to take.
    from chumicro_screens.framebuf_canvas import FramebufCanvas

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
                 column_window: bytes, row_window: bytes, strip_view: memoryview,
                 locking: bool, row_count: int = 0, items_per_row: int = 0,
                 offset: int = 0, count: int = 0) -> None:
    """One self-contained transfer: window commands, then pixel data.

    ``locking`` takes and releases a ``busio.SPI`` lock around the
    transfer, which is how CircuitPython shares a bus; ``machine.SPI``
    has no lock and gets none.  With ``row_count`` set the pixel data
    goes one ``busio`` write per row, ``count`` items from ``offset``
    and then every ``items_per_row``, in the buffer's own items: the
    rows of a narrowed window are not contiguous in a strip laid out at
    the frame's width, and ``busio.SPI.write`` bounds a write with
    ``start`` and ``end`` so no slice is allocated.  ``machine.SPI`` has
    no such bounds, which is why the MicroPython path re-lays the strip
    at the window's width and sends it whole.
    """
    if locking:
        while not spi.try_lock():
            pass
    try:
        chip_select(0)
        data_command(0)
        spi.write(_COLUMN_ADDRESS_COMMAND)
        data_command(1)
        spi.write(column_window)
        data_command(0)
        spi.write(_ROW_ADDRESS_COMMAND)
        data_command(1)
        spi.write(row_window)
        data_command(0)
        spi.write(_MEMORY_WRITE_COMMAND)
        data_command(1)
        if row_count:
            row = 0
            while row < row_count:
                spi.write(strip_view, start=offset, end=offset + count)
                offset += items_per_row
                row += 1
        else:
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


def _frame(bitmap: object, frame_bits: int, frame_bitmap: object) -> object:
    """Return the app's pre-allocated frame bitmap after checking its shape, or allocate one."""
    if bitmap is None:
        return frame_bitmap(WIDTH, HEIGHT, 65536 if frame_bits == 16 else _PALETTE_SIZE)
    if (bitmap.width, bitmap.height, bitmap.bits_per_value) != (WIDTH, HEIGHT, frame_bits):
        raise ValueError("bitmap must be 240 by 240 at frame_bits bits per pixel")
    return bitmap


def _strip_views(view: memoryview, transfer_rows: int, height: int) -> list:
    """Pre-slice one view per strip so an advance allocates nothing.

    ``view`` holds ``height`` rows: the whole frame, so each strip's
    view starts at its own rows, or one ``transfer_rows``-row strip
    buffer that every strip shares, so each view starts at row 0.  The
    view may count bytes or 16-bit items, depending on the buffer
    behind it, so a row's length in items is measured rather than
    assumed.
    """
    items_per_row = len(view) // height
    strips = []
    for row_start, row_count, window in _strip_bounds(transfer_rows):
        first = row_start * items_per_row if height == HEIGHT else 0
        strips.append((row_start, row_count, window,
                       view[first:first + row_count * items_per_row]))
    return strips


class GC9A01A:
    """Round TFT panel drawn in raw 16-bit color; flush through ScreenService.

    The bus objects are injected: the app constructs the SPI bus and
    the three control pins and passes them in, so the driver never
    imports ``machine`` or ``busio``.  Pins follow the callable protocol
    (``pin(1)`` drives high); the SPI object needs ``write``, plus
    ``try_lock`` and ``unlock`` when it is a ``busio.SPI``.

    ``frame`` stores pixels in the panel's on-wire byte order, so
    colors come from ``color565``, never from raw RGB565 literals.  On
    MicroPython it is a ``chumicro_screens.framebuf_canvas.FramebufCanvas``
    in ``RGB565``: framebuf's drawing methods, ``Font`` text in a
    ``color565`` value, and a flush that sends only the strips
    covering the rows drawn since the last one, at full width.  On
    CircuitPython it is a ``displayio.Bitmap`` for ``bitmaptools`` to
    draw on, and every flush sends the whole frame.  Either way the
    frame is 115,200 bytes, so this class wants a PSRAM-class board on
    MicroPython and leaves a Pi Pico W about 43 KB under CircuitPython
    once the driver's own code is loaded; the portable
    ``GC9A01AIndexed`` is the smaller shape on MicroPython.

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
        bitmap: On CircuitPython, a 240 by 240 ``displayio.Bitmap`` with
            65536 values to use as the frame instead of allocating one.
            Allocate it before importing anything, so it takes the
            heap's largest block ahead of this module's own compile,
            which on a Pi Pico W can leave no block that size.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, spi: object, chip_select: object, data_command: object,
                 reset: object, *, transfer_rows: int = 10, bitmap: object | None = None,
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
            from chumicro_screens.bitmap_canvas import frame_bitmap
            self.frame = _frame(bitmap, 16, frame_bitmap)
            view = memoryview(self.frame)
        else:
            if bitmap is not None:
                raise ValueError("bitmap applies to CircuitPython; MicroPython allocates its frame")
            # The frame needs one contiguous block, so reclaim the compile
            # scratch the import chain left interleaved with live objects.
            gc.collect()
            self._buffer = bytearray(WIDTH * HEIGHT * 2)
            view = memoryview(self._buffer)
            self.frame = FramebufCanvas(self._buffer, WIDTH, HEIGHT, framebuf.RGB565)
        self._strips = _strip_views(view, transfer_rows, HEIGHT)
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        _bring_up(spi, chip_select, data_command, reset, sleep_ms, self._locking)

    def flush(self) -> object:
        """Send the strips covering the drawn rows, one per advance; the panel protocol."""
        strips = self._strips
        if framebuf is None:
            index = 0
            last = len(strips) - 1
        else:
            x1, y1, x2, y2 = self.frame.take_dirty()
            if x1 >= x2:
                return
            transfer_rows = strips[0][1]
            index = y1 // transfer_rows
            last = (y2 - 1) // transfer_rows
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        locking = self._locking
        first = True
        while index <= last:
            if not first:
                yield
            first = False
            _, _, window, view = strips[index]
            index += 1
            _write_strip(spi, chip_select, data_command, _FULL_WIDTH_WINDOW,
                         window, view, locking)


class GC9A01AIndexed:
    """Round TFT panel as the portable canvas: palette indexes, one API on both runtimes.

    Drawing on ``frame`` uses palette indexes as colors: assign an index
    a color with ``set_color``, then draw with the index.  Index 0
    starts black.  ``frame`` offers framebuf's method vocabulary on
    both runtimes: ``fill``, ``pixel``, ``hline``, ``vline``, ``line``,
    ``rect``, ``fill_rect``, ``ellipse``, ``poly``, ``blit``, ``text``.
    On MicroPython it is a ``chumicro_screens.framebuf_canvas.FramebufCanvas``,
    a ``framebuf.FrameBuffer`` that also records what it drew; on
    CircuitPython it is a ``chumicro_screens.bitmap_canvas.BitmapCanvas``
    over a ``displayio.Bitmap`` that draws circles rather than general
    ellipses, polygon outlines rather than fills, and its ``text`` in
    the runtime's own built-in font, whose metrics differ from
    framebuf's 8x8.  ``chumicro_screens.fonts.Font`` draws a converted
    font at the same pixels on both runtimes.

    A flush sends only what changed.  The canvas records the bounds
    of every primitive since the last flush, and the flush sends the
    strips covering that rectangle, each windowed to its columns, so
    an app that redraws a few digits pays for a few advances and an
    app that fills the frame pays for the whole frame.  A frame with
    nothing drawn on it flushes in one empty advance.  Redraw only what
    changed to collect the saving: clear the region with ``fill_rect``
    and draw over it, rather than ``fill`` and redraw everything.
    Every ``set_color`` after the first flush marks the whole frame,
    since drawn pixels holding the index change color.  ``dirty(x, y,
    width, height)`` on the canvas marks a region drawn behind its
    back, and ``take_dirty()`` is what the flush reads.

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
    palette wants ``transfer_rows=2``.  The passes cover the strip's
    full width whatever the window, so a narrow window on that path
    saves bus time and the copy but not the passes.  ``frame_bits=16``
    trades RAM for that time on CircuitPython: a 16-bit frame (115,200
    bytes) holds colors rather than indexes, so no expansion runs and
    a 6-row strip streams in 1.4 ms mean and 2.0 ms worst, 62 ms a
    frame, but ``set_color`` applies to later drawing only, and a Pi
    Pico W holds the frame with about 43 KB to spare only when the
    panel is constructed before anything else.  MicroPython's frame is
    8-bit whatever ``frame_bits`` says.

    Construct early: the frame needs one contiguous block, which a
    fragmented heap may no longer hold.

    ``transfer_rows`` defaults to 6, or 3 on the CircuitPython 8-bit
    frame.  Sizing datum from the Pi Pico W bench under MicroPython,
    where ``machine.SPI`` clamps a 40 MHz request to 24 MHz: the 6-row
    strip measured 3.6 ms at worst, inside a 5 ms tick, and a full frame
    crosses in 40 advances, about 123 ms, fitted with a model of 0.2 ms
    fixed plus 0.5 ms per row, so taller strips barely shorten the
    frame.  A faster chip can raise ``transfer_rows`` as its own bench
    allows.  Strips sit on a fixed grid of ``transfer_rows`` rows, so a
    partial flush sends whole strips from the one holding the top dirty
    row to the one holding the bottom.

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
        bitmap: On CircuitPython, a 240 by 240 ``displayio.Bitmap`` at
            ``frame_bits`` bits per pixel to use as the frame instead of
            allocating one.  Allocate it before importing anything, so
            it takes the heap's largest block ahead of this module's
            own compile, which on a Pi Pico W can leave no block for a
            16-bit frame.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, spi: object, chip_select: object, data_command: object,
                 reset: object, *, transfer_rows: int | None = None,
                 frame_bits: int = 8, bitmap: object | None = None,
                 sleep_ms: object | None = None) -> None:
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
        self._column_window = bytearray(4)
        self._strip = None
        self._assigned = None
        self._passes = None
        if framebuf is None:
            import bitmaptools
            import displayio
            import terminalio

            from chumicro_screens.bitmap_canvas import BitmapCanvas, frame_bitmap
            self._tools = bitmaptools
            self._palette_frame = None
            self._strip_frame = None
            self._colors = array.array("H", bytes(_PALETTE_SIZE * 2))
            bitmap = _frame(bitmap, frame_bits, frame_bitmap)
            if frame_bits == 16:
                canvas_colors = self._colors
                self._strips = _strip_views(memoryview(bitmap), transfer_rows, HEIGHT)
            else:
                canvas_colors = bytes(range(_PALETTE_SIZE))
                self._assigned = bytearray(_PALETTE_SIZE)
                self._assigned[0] = 1
                self._strip = displayio.Bitmap(WIDTH, transfer_rows, 65536)
                self._strips = _strip_views(memoryview(self._strip), transfer_rows,
                                            transfer_rows)
            self._bitmap = bitmap
            self.frame = BitmapCanvas(bitmap, canvas_colors, bitmaptools,
                                      terminalio.FONT, displayio)
        else:
            if bitmap is not None:
                raise ValueError("bitmap applies to CircuitPython; MicroPython allocates its frame")
            # The frame needs one contiguous block, so reclaim the compile
            # scratch the import chain left interleaved with live objects.
            gc.collect()
            self._buffer = bytearray(WIDTH * HEIGHT)
            self.frame = FramebufCanvas(self._buffer, WIDTH, HEIGHT, framebuf.GS8)
            buffer = bytearray(transfer_rows * _ROW_BYTES)
            self._strip_frame = framebuf.FrameBuffer(buffer, WIDTH, transfer_rows,
                                                     framebuf.RGB565)
            self._palette_frame = framebuf.FrameBuffer(
                bytearray(_PALETTE_SIZE * 2), _PALETTE_SIZE, 1, framebuf.RGB565)
            self._strips = _strip_views(memoryview(buffer), transfer_rows, transfer_rows)
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        _bring_up(spi, chip_select, data_command, reset, sleep_ms, self._locking)

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        """Assign palette entry ``index`` the given 8-bit channels.

        Drawing ``index`` on ``frame`` renders this color from the next
        flush on, and already-drawn pixels holding the index change with
        it, so the call marks the whole frame for that flush.  On a
        16-bit CircuitPython frame the color applies to drawing done
        after the call instead, and nothing is marked.

        Args:
            index: Palette slot, 0 to 255.
            red: Red channel, 0 to 255.
            green: Green channel, 0 to 255.
            blue: Blue channel, 0 to 255.
        """
        value = color565(red, green, blue)
        if self._palette_frame is not None:
            self._palette_frame.pixel(index, 0, value)
            self.frame.dirty(0, 0, WIDTH, HEIGHT)
            return
        self._colors[index] = value
        if self._assigned is not None:
            self._assigned[index] = 1
            self._passes = None
            self.frame.dirty(0, 0, WIDTH, HEIGHT)

    def flush(self) -> object:
        """Expand and send one strip per advance over the drawn rectangle; the panel protocol.

        The identifiers here are kept to names the firmware already
        interns where the wording allows: a new qstr pool allocated
        during this module's compile lands above its parse tree and can
        cost a Pi Pico W the block a 16-bit frame needs.
        """
        frame = self.frame
        left, y1, right, y2 = frame.take_dirty()
        if left >= right:
            return
        width = right - left
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        locking = self._locking
        strips = self._strips
        transfer_rows = strips[0][1]
        window = self._column_window
        window[0] = left >> 8
        window[1] = left & 0xFF
        window[2] = (right - 1) >> 8
        window[3] = (right - 1) & 0xFF
        strip_frame = self._strip_frame
        palette_frame = self._palette_frame
        strip_view = None
        strip = self._strip
        if strip_frame is not None:
            if width != WIDTH:
                # A narrowed strip is re-laid at the window's width so
                # its rows are contiguous for machine.SPI, which writes
                # whole buffers only.  This is the one flush that
                # allocates past its generator: one FrameBuffer and one
                # view, 64 bytes, per partial frame.
                strip_frame = framebuf.FrameBuffer(strips[0][3], width, transfer_rows,
                                                   framebuf.RGB565)
                strip_view = strips[0][3][:transfer_rows * width * 2]
        elif strip is not None:
            tools = self._tools
            bitmap = self._bitmap
            passes = self._passes
            if passes is None:
                from chumicro_screens.bitmap_canvas import expansion_passes
                passes = self._passes = expansion_passes(self._colors, self._assigned)
        index = y1 // transfer_rows
        last = (y2 - 1) // transfer_rows
        first = True
        while index <= last:
            if not first:
                yield
            first = False
            row_start, row_count, row_window, view = strips[index]
            index += 1
            if strip_frame is not None:
                strip_frame.blit(frame, -left, -row_start, -1, palette_frame)
                if strip_view is not None:
                    view = strip_view
                    if row_count != transfer_rows:
                        view = strip_view[:row_count * width * 2]
                _write_strip(spi, chip_select, data_command, window, row_window,
                             view, locking)
                continue
            items_per_row = len(view) // row_count
            if strip is not None:
                tools.blit(strip, bitmap, 0, 0, x1=left, y1=row_start, x2=right,
                           y2=row_start + row_count)
                for old, new in passes:
                    tools.replace_color(strip, old, new)
                offset = 0
            else:
                offset = left * (items_per_row // WIDTH)
            if width == WIDTH:
                _write_strip(spi, chip_select, data_command, window, row_window,
                             view, locking)
            else:
                _write_strip(spi, chip_select, data_command, window, row_window,
                             view, locking, row_count, items_per_row, offset,
                             width * (items_per_row // WIDTH))
