"""GC9A01A: a 240x240 round color TFT as a chumicro-screens panel.

The panel holds its own frame, so the driver keeps none: ``GC9A01A``
is the bring-up sequence plus ``write_strip``, which sends the rows a
``Screen`` painted into the panel's strip as one self-contained
transfer (column and row window, then pixel data).  The strip is
``rows`` rows of RGB565 in the panel's wire byte order, a
``framebuf.FrameBuffer`` on MicroPython and a 16-bit
``displayio.Bitmap`` on CircuitPython, and ``color565`` packs a color
into the value items hold.

An 8-row strip is 3,840 bytes and spends about 2 ms on the bus at
24 MHz, the clock an RP2040 gives either runtime (``machine.SPI``
clamps a 40 MHz request to 24 MHz there).  With the counter scene, a
ring, a caption, and a count, a Pi Pico W paints and sends one in
2.6 ms mean and 2.8 ms worst under MicroPython and 3.9 ms and 4.5 ms
under CircuitPython, a full paint in 77 ms and 116 ms across 30
advances with the loop live throughout, and a count's two strips in
5 ms and 9 ms.

Construction blocks 330 to 365 ms, depending on the board, while the
panel resets and runs its initialization sequence.
"""

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
    from chumicro_screens.framebuf_strip import FramebufStrip

try:
    from time import sleep_ms as _sleep_ms
except ImportError:
    def _sleep_ms(duration_ms: int) -> None:
        """Millisecond sleep for runtimes without ``time.sleep_ms``."""
        time.sleep(duration_ms / 1000)

WIDTH = const(240)
HEIGHT = const(240)

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
    """Pack 8-bit red, green, blue into the value ``GC9A01A`` items draw in.

    The value is RGB565 in the panel's on-wire byte order.  Both strip
    canvases store 16-bit pixels low byte first while the panel reads
    high byte first, so the helper pre-swaps; a raw RGB565 literal like
    ``0xF800`` renders the wrong color.

    Args:
        red: Red channel, 0 to 255.
        green: Green channel, 0 to 255.
        blue: Blue channel, 0 to 255.

    Returns:
        The 16-bit value to give a ``Screen`` item.
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


class GC9A01A:
    """The round TFT as a ``Screen`` panel: bring-up, then one strip write per advance.

    The bus and pins are injected: the app constructs the SPI bus and
    the three output pins (``chumicro_compat.wiring`` resolves them
    from GPIO numbers on both runtimes) and passes them in.  A pin is
    a callable taking 0 or 1; the bus needs ``write``, and a
    ``busio.SPI`` is locked around each transfer.

    Args:
        spi: SPI bus wired to the panel, clock and data lines.
        chip_select: Output pin on the panel's CS line.
        data_command: Output pin on the panel's DC line.
        reset: Output pin on the panel's RST line.
        rows: Rows per strip, a divisor of 240.  Each row is 480 bytes
            of strip and about 0.25 ms on the bus; fewer rows shorten
            every advance and add advances to a frame.
        sleep_ms: Millisecond-sleep callable used during panel init.
            Defaults to the real clock.
    """

    def __init__(self, spi: object, chip_select: object, data_command: object,
                 reset: object, *, rows: int = 8, sleep_ms: object | None = None) -> None:
        if rows < 1 or HEIGHT % rows:
            raise ValueError("rows must divide 240")
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        self._spi = spi
        self._chip_select = chip_select
        self._data_command = data_command
        self._locking = hasattr(spi, "try_lock")
        self.width = WIDTH
        self.height = HEIGHT
        if framebuf is None:
            from chumicro_screens.bitmap_strip import BitmapStrip
            self.strip = BitmapStrip(WIDTH, rows)
            self._view = self.strip.buffer
        else:
            self.strip = FramebufStrip(bytearray(WIDTH * rows * 2), WIDTH, rows, framebuf.RGB565,
                                       narrowable=True)
            self._view = None
        self._column_window = bytearray(4)
        self._row_window = bytearray(4)
        if self._locking:
            while not spi.try_lock():
                pass
        try:
            _reset_panel(reset, sleep_ms)
            _run_init(spi, chip_select, data_command, sleep_ms)
        finally:
            if self._locking:
                spi.unlock()

    def write_strip(self, top: int, count: int, left: int, right: int) -> None:
        """Send columns ``left`` to ``right`` of the strip to ``count`` panel rows from ``top``.

        One self-contained transfer: column and row window, then the
        pixels.  On CircuitPython a narrowed window goes one bounded
        ``busio`` write per row from the full-width strip; on
        MicroPython the strip laid itself out at the window's width,
        so its view is the whole transfer.

        Args:
            top: Panel row the strip's row 0 holds.
            count: Rows to send, the strip's full height.
            left: First column to send.
            right: One past the last column to send.
        """
        columns = self._column_window
        column_end = right - 1
        columns[0] = left >> 8
        columns[1] = left & 0xFF
        columns[2] = column_end >> 8
        columns[3] = column_end & 0xFF
        window = self._row_window
        row_end = top + count - 1
        window[0] = top >> 8
        window[1] = top & 0xFF
        window[2] = row_end >> 8
        window[3] = row_end & 0xFF
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
        locking = self._locking
        if locking:
            while not spi.try_lock():
                pass
        try:
            chip_select(0)
            data_command(0)
            spi.write(_COLUMN_ADDRESS_COMMAND)
            data_command(1)
            spi.write(columns)
            data_command(0)
            spi.write(_ROW_ADDRESS_COMMAND)
            data_command(1)
            spi.write(window)
            data_command(0)
            spi.write(_MEMORY_WRITE_COMMAND)
            data_command(1)
            if framebuf is not None:
                spi.write(self.strip.view)
            elif right - left == WIDTH:
                spi.write(self._view)
            else:
                view = self._view
                offset = left
                row = 0
                while row < count:
                    spi.write(view, start=offset, end=offset + right - left)
                    offset += WIDTH
                    row += 1
            chip_select(1)
        finally:
            if locking:
                spi.unlock()
