"""GC9A01A driver: a 240x240 round color TFT as a chumicro-screens panel.

The driver owns a full RGB565 frame buffer (115,200 bytes), so it needs
a board whose free heap holds one; PSRAM-class boards qualify, 256 KB
boards do not.  Drawing happens on ``frame``, a
``framebuf.FrameBuffer`` in RGB565, at C speed.  ``flush()`` is the
ScreenService panel protocol: each advance sends one strip of
``transfer_rows`` rows as a self-contained transfer (window, then
memory write), so a full frame spreads across ticks instead of
blocking one.

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
        self._buffer_view = memoryview(self._buffer)
        # Construction-time import: keeps the module importable on
        # CPython, where framebuf does not exist.
        import framebuf
        self.frame = framebuf.FrameBuffer(self._buffer, WIDTH, HEIGHT,
                                          framebuf.RGB565)
        self._strips = self._build_strips(transfer_rows)
        if sleep_ms is None:
            sleep_ms = _sleep_ms
        self._reset_panel(sleep_ms)
        self._run_init(sleep_ms)

    def _build_strips(self, transfer_rows: int) -> list:
        """Precompute each strip's row window and buffer view once."""
        strips = []
        row_start = 0
        while row_start < HEIGHT:
            row_count = transfer_rows
            if row_start + row_count > HEIGHT:
                row_count = HEIGHT - row_start
            row_end = row_start + row_count - 1
            window = bytes((row_start >> 8, row_start & 0xFF,
                            row_end >> 8, row_end & 0xFF))
            offset = row_start * _ROW_BYTES
            view = self._buffer_view[offset:offset + row_count * _ROW_BYTES]
            strips.append((window, view))
            row_start += row_count
        return strips

    def _reset_panel(self, sleep_ms: object) -> None:
        reset = self._reset
        reset(1)
        sleep_ms(5)
        reset(0)
        sleep_ms(20)
        reset(1)
        sleep_ms(150)

    def _run_init(self, sleep_ms: object) -> None:
        sequence = _INIT_SEQUENCE
        index = 0
        while index < len(sequence):
            command_byte = sequence[index]
            control = sequence[index + 1]
            count = control & 0x7F
            self._write_command(command_byte,
                                sequence[index + 2:index + 2 + count])
            index += 2 + count
            if control & 0x80:
                sleep_ms(sequence[index])
                index += 1

    def _write_command(self, command_byte: int, data: bytes) -> None:
        """Send one command with its data bytes; init path only, allocates."""
        chip_select = self._chip_select
        data_command = self._data_command
        spi = self._spi
        chip_select(0)
        data_command(0)
        spi.write(bytes((command_byte,)))
        if data:
            data_command(1)
            spi.write(data)
        chip_select(1)

    def flush(self) -> object:
        """Send the frame one strip per advance; the panel protocol."""
        write_strip = self._write_strip
        first = True
        for window, view in self._strips:
            if not first:
                yield
            first = False
            write_strip(window, view)

    def _write_strip(self, row_window: bytes, strip_view: memoryview) -> None:
        """One self-contained transfer: window commands, then pixel data."""
        spi = self._spi
        chip_select = self._chip_select
        data_command = self._data_command
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
