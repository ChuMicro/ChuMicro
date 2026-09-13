"""``FramebufStrip``: the MicroPython strip canvas, a ``framebuf.FrameBuffer`` a few rows tall.

The panel builds the ``FrameBuffer`` over the bytes it sends, in its
own pixel format, and hands it in; the strip paints the ``Screen``
items into it with ``top`` as the panel row its row 0 holds.  Every
primitive is one framebuf call with the row offset applied, since
framebuf clips whatever falls outside the buffer.  Built-in text is
framebuf's 8 by 8 font; a ``chumicro_screens.fonts.Font`` blits its
glyphs through a palette in the strip's format.
"""

__chumicro_runtimes__ = ("micropython",)


class FramebufStrip:
    """``width`` by ``rows`` pixels of the panel, drawn through framebuf.

    Args:
        framebuffer: The ``framebuf.FrameBuffer`` over the panel's
            strip bytes.
        width: Strip width in pixels, the panel's width.
        rows: Strip height in pixels; a flush paints the panel in bands
            this tall.
        pixel_format: The framebuf format ``framebuffer`` was built
            with, which a ``Font`` needs for its palette.
    """

    glyph_width = 8
    glyph_height = 8

    def __init__(self, framebuffer: object, width: int, rows: int, pixel_format: int) -> None:
        self.framebuffer = framebuffer
        self.width = width
        self.rows = rows
        self.pixel_format = pixel_format
        self.top = 0

    def clear(self, value: int) -> None:
        self.framebuffer.fill(value)

    def fill_rect(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.framebuffer.fill_rect(x, y - self.top, width, height, value)

    def box(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.framebuffer.rect(x, y - self.top, width, height, value)

    def line(self, x0: int, y0: int, x1: int, y1: int, value: int) -> None:
        top = self.top
        self.framebuffer.line(x0, y0 - top, x1, y1 - top, value)

    def prepare_ring(self, x_center: int, y_center: int, radius: int, cache: dict) -> None:
        """Nothing to prepare: framebuf's ``ellipse`` clips at the strip's edges."""

    def ring(self, x_center: int, y_center: int, radius: int, value: int,
             cache: dict) -> None:
        self.framebuffer.ellipse(x_center, y_center - self.top, radius, radius, value)

    def prepare_text(self, string: str, value: int, font: object | None, cache: list) -> None:
        """Nothing to prepare: text blits straight from the font on every paint."""

    def text(self, string: str, x: int, y: int, value: int, font: object | None,  # noqa: CHU001 - framebuf's own names
             cache: list) -> None:
        y -= self.top  # noqa: CHU001 - framebuf's own names
        if font is None:
            self.framebuffer.text(string, x, y, value)
        else:
            font.draw(self.framebuffer, self.pixel_format, string, x, y, value)

    def blit(self, source: object, x: int, y: int, key: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.framebuffer.blit(source, x, y - self.top, key)
