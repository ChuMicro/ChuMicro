"""``FramebufStrip``: the MicroPython strip canvas, a ``framebuf.FrameBuffer`` a few rows tall.

The panel hands in the bytes it sends and their framebuf format; the
strip paints the ``Screen`` items into them with ``top`` as the panel
row its row 0 holds and ``left`` as the panel column its column 0
holds.  Every primitive is one framebuf call with those offsets
applied, since framebuf clips whatever falls outside the buffer.
Built-in text is framebuf's 8 by 8 font; a
``chumicro_screens.fonts.Font`` blits its glyphs through a palette in
the strip's format.

A panel that windows its columns lets the strip narrow itself to the
flush's dirty columns: ``window`` lays a ``FrameBuffer`` of that width
over the same bytes, so the strip's ``view`` is exactly the bytes to
send, laid out contiguously, which ``machine.SPI.write`` needs since
it writes whole buffers only.
"""

__chumicro_runtimes__ = ("micropython",)

try:
    import framebuf
except ImportError:
    framebuf = None


class FramebufStrip:
    """``width`` by ``rows`` pixels of the panel, drawn through framebuf.

    Args:
        buffer: The bytes the panel sends, ``rows`` rows of ``width``
            pixels in ``pixel_format``.
        width: Strip width in pixels, the panel's width.
        rows: Strip height in pixels; a flush paints the panel in bands
            this tall.
        pixel_format: The framebuf format of ``buffer``.
        narrowable: Whether the panel sends a column window, so the
            strip may narrow to the flush's dirty columns.  Only the
            byte-per-pixel formats (``RGB565``, ``GS8``) narrow.
    """

    glyph_width = 8
    glyph_height = 8

    def __init__(self, buffer: object, width: int, rows: int, pixel_format: int,
                 narrowable: bool = False) -> None:
        self.buffer = buffer
        self.width = width
        self.rows = rows
        self.pixel_format = pixel_format
        self.top = 0
        self.left = 0
        self.window_width = width
        self._full = framebuf.FrameBuffer(buffer, width, rows, pixel_format)
        self._full_view = memoryview(buffer)
        self.framebuffer = self._full
        self.view = self._full_view
        self._narrowable = narrowable and pixel_format in (framebuf.RGB565, framebuf.GS8)
        self._bytes_per_pixel = 2 if pixel_format == framebuf.RGB565 else 1

    def window(self, left: int, right: int) -> None:
        """Lay the strip out at the columns ``left`` to ``right`` for this flush.

        A full-width window, or a panel that cannot window, keeps the
        prebuilt full-width layout and allocates nothing; a narrower
        one costs a ``FrameBuffer`` and a view per flush.
        """
        width = right - left
        if not self._narrowable or width == self.width:
            self.left = 0
            self.window_width = self.width
            self.framebuffer = self._full
            self.view = self._full_view
            return
        self.left = left
        self.window_width = width
        self.framebuffer = framebuf.FrameBuffer(self.buffer, width, self.rows, self.pixel_format)
        self.view = self._full_view[:self.rows * width * self._bytes_per_pixel]

    def clear(self, value: int) -> None:
        self.framebuffer.fill(value)

    def fill_rect(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.framebuffer.fill_rect(x - self.left, y - self.top, width, height, value)

    def box(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.framebuffer.rect(x - self.left, y - self.top, width, height, value)

    def line(self, x0: int, y0: int, x1: int, y1: int, value: int) -> None:
        top = self.top
        left = self.left
        self.framebuffer.line(x0 - left, y0 - top, x1 - left, y1 - top, value)

    def prepare_ring(self, x_center: int, y_center: int, radius: int, cache: dict) -> None:
        """Nothing to prepare: framebuf's ``ellipse`` clips at the strip's edges."""

    def ring(self, x_center: int, y_center: int, radius: int, value: int,
             cache: dict) -> None:
        self.framebuffer.ellipse(x_center - self.left, y_center - self.top, radius, radius, value)

    def prepare_text(self, string: str, value: int, font: object | None, cache: list) -> None:
        """Nothing to prepare: text blits straight from the font on every paint."""

    def text(self, string: str, x: int, y: int, value: int, font: object | None,  # noqa: CHU001 - framebuf's own names
             cache: list) -> None:
        x -= self.left  # noqa: CHU001 - framebuf's own names
        y -= self.top  # noqa: CHU001 - framebuf's own names
        if font is None:
            self.framebuffer.text(string, x, y, value)
        else:
            font.draw(self.framebuffer, self.pixel_format, string, x, y, value)

    def blit(self, source: object, x: int, y: int, key: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.framebuffer.blit(source, x - self.left, y - self.top, key)
