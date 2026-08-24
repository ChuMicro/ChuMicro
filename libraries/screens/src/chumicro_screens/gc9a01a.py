"""GC9A01A drivers: a 240x240 round color TFT as chumicro-screens panels.

Two panel classes share the bus protocol and initialization sequence
and differ in how the frame lives in RAM:

- ``GC9A01A`` owns a full RGB565 frame buffer (115,200 bytes) and
  needs a board whose free heap holds one; PSRAM-class boards
  qualify.  Drawing happens at 16-bit depth.
- ``GC9A01AIndexed`` owns an 8-bit indexed frame (57,600 bytes) plus
  a 256-entry RGB565 palette, fitting 256 KB-class boards.  Each
  flush advance expands one strip through the palette with
  ``FrameBuffer.blit``, which converts at C speed.

Either way drawing happens on ``frame``, a ``framebuf.FrameBuffer``,
and ``flush()`` is the ScreenService panel protocol: each advance
sends one strip of ``transfer_rows`` rows as a self-contained
transfer (window, then memory write), so a full frame spreads across
ticks instead of blocking one.

Construction blocks about 350 ms while the panel resets and runs its
initialization sequence.
"""

__chumicro_runtimes__ = ("micropython",)

import time

WIDTH = 240
HEIGHT = 240

_ROW_BYTES = WIDTH * 2
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
    """Pack 8-bit red, green, blue into the value ``frame`` drawing takes.

    The value is RGB565 in the panel's on-wire byte order.  framebuf
    stores 16-bit pixels low byte first while the panel reads high
    byte first, so the helper pre-swaps; a raw RGB565 literal like
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


def _sleep_ms(duration_ms: int) -> None:
    """Sleep via ``time.sleep_ms`` when present, otherwise ``time.sleep``."""
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if runtime_sleep_ms is not None:
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


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


def _write_strip(spi: object, chip_select: object, data_command: object,
                 row_window: bytes, strip_view: memoryview) -> None:
    """One self-contained transfer: window commands, then pixel data."""
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


class GC9A01A:
    """Round TFT panel: draw on ``frame``, flush through ScreenService.

    The bus objects are injected: the app constructs the SPI bus and
    the three control pins and passes them in, so the driver never
    imports ``machine``.  Pins follow the callable protocol
    (``pin(1)`` drives high); the SPI object needs only ``write``.

    ``frame`` stores pixels in the panel's on-wire byte order, so
    colors come from ``color565``, never from raw RGB565 literals.

    ``transfer_rows`` bounds one flush advance.  Sizing datum from the
    LOLIN S2 Mini bench at 40 MHz SPI: a 10-row strip averages 3.3 ms
    with a worst case under 4 ms, inside a 5 ms tick, and a full frame
    crosses in 24 advances, about 80 ms.

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
        self._reset = reset
        self.width = WIDTH
        self.height = HEIGHT
        self._buffer = bytearray(WIDTH * HEIGHT * 2)
        buffer_view = memoryview(self._buffer)
        # Construction-time import: keeps the module importable on
        # CPython, where framebuf does not exist.
        import framebuf
        self.frame = framebuf.FrameBuffer(self._buffer, WIDTH, HEIGHT,
                                          framebuf.RGB565)
        self._strips = [
            (window, buffer_view[row_start * _ROW_BYTES:
                                 (row_start + row_count) * _ROW_BYTES])
            for row_start, row_count, window in _strip_bounds(transfer_rows)]
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        _reset_panel(reset, sleep_ms)
        _run_init(spi, chip_select, data_command, sleep_ms)

    def flush(self) -> object:
        """Send the frame one strip per advance; the panel protocol."""
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        first = True
        for window, view in self._strips:
            if not first:
                yield
            first = False
            _write_strip(spi, chip_select, data_command, window, view)


class GC9A01AIndexed:
    """Round TFT panel for 256 KB-class boards: 8-bit frame, palette.

    The full-color :class:`GC9A01A` frame is 115,200 bytes; this
    variant holds the frame at one byte per pixel (57,600 bytes) plus
    a 256-entry palette, about half the RAM, so a Pico W-class heap
    fits it.  Drawing on ``frame`` uses palette indexes as colors:
    assign an index a color with ``set_color``, then draw with the
    index.  Index 0 starts black.

    Each flush advance expands one strip of ``transfer_rows`` rows
    through the palette into a small RGB565 strip buffer with
    ``FrameBuffer.blit``, which runs the conversion in C, then sends
    the strip.  Bus wiring and injection match :class:`GC9A01A`.

    Construct early: the 57,600-byte frame needs a contiguous block,
    which a fragmented heap may no longer hold.

    ``transfer_rows`` defaults for the driver's target class.  Sizing
    datum from the Pi Pico W bench, where ``machine.SPI`` clamps a
    40 MHz request to 24 MHz: per-advance cost is about 0.2 ms fixed
    plus 0.5 ms per row, so a 6-row strip peaks at 3.2 ms inside a
    5 ms tick and a full frame crosses in 40 advances, about 122 ms.
    Taller strips barely shorten the frame; a faster chip can raise
    ``transfer_rows`` as its own bench allows.

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
                 reset: object, *, transfer_rows: int = 6,
                 sleep_ms: object | None = None) -> None:
        if not 1 <= transfer_rows <= HEIGHT:
            raise ValueError("transfer_rows must be 1 to 240")
        self._spi = spi
        self._chip_select = chip_select
        self._data_command = data_command
        self._reset = reset
        self.width = WIDTH
        self.height = HEIGHT
        self._buffer = bytearray(WIDTH * HEIGHT)
        # Construction-time import: keeps the module importable on
        # CPython, where framebuf does not exist.
        import framebuf
        self.frame = framebuf.FrameBuffer(self._buffer, WIDTH, HEIGHT,
                                          framebuf.GS8)
        strip_buffer = bytearray(transfer_rows * _ROW_BYTES)
        strip_view = memoryview(strip_buffer)
        self._strip_frame = framebuf.FrameBuffer(strip_buffer, WIDTH,
                                                 transfer_rows,
                                                 framebuf.RGB565)
        self._palette_frame = framebuf.FrameBuffer(bytearray(256 * 2), 256, 1,
                                                   framebuf.RGB565)
        self._strips = [
            (row_start, window, strip_view[:row_count * _ROW_BYTES])
            for row_start, row_count, window in _strip_bounds(transfer_rows)]
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        _reset_panel(reset, sleep_ms)
        _run_init(spi, chip_select, data_command, sleep_ms)

    def set_color(self, index: int, red: int, green: int, blue: int) -> None:
        """Assign palette entry ``index`` the given 8-bit channels.

        Drawing ``index`` on ``frame`` renders this color from the
        next flush on; already-drawn pixels holding the index change
        with it.

        Args:
            index: Palette slot, 0 to 255.
            red: Red channel, 0 to 255.
            green: Green channel, 0 to 255.
            blue: Blue channel, 0 to 255.
        """
        self._palette_frame.pixel(index, 0, color565(red, green, blue))

    def flush(self) -> object:
        """Expand and send one strip per advance; the panel protocol."""
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        frame = self.frame
        strip_frame = self._strip_frame
        palette_frame = self._palette_frame
        first = True
        for row_start, window, view in self._strips:
            if not first:
                yield
            first = False
            strip_frame.blit(frame, 0, -row_start, -1, palette_frame)
            _write_strip(spi, chip_select, data_command, window, view)
