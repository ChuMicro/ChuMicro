"""framebuf's drawing vocabulary over a 16-bit ``displayio.Bitmap``.

``BitmapCanvas`` is what ``GC9A01AIndexed.frame`` is on CircuitPython:
the same method names an app calls on a ``framebuf.FrameBuffer`` under
MicroPython, with palette indexes as colors, so one drawing file runs on
both runtimes.  Each primitive resolves its index through the panel's
palette as it draws, so the bitmap holds the panel's own 16-bit values
and streams to it without conversion.
"""

__chumicro_runtimes__ = ("circuitpython",)

import array

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

_PALETTE_SIZE = const(256)


class BitmapCanvas:
    """A ``displayio.Bitmap`` drawn with ``bitmaptools``, colors as palette indexes.

    Coordinates clip to the frame as framebuf's do.  ``ellipse`` draws
    circles only and ``poly`` outlines only, since those are the shapes
    ``bitmaptools`` has a C path for.  ``text`` renders the runtime's
    built-in font, and ``blit_bits`` is the 1-bit glyph primitive under
    it that ``chumicro_screens.fonts.Font`` draws converted fonts
    through.

    Args:
        bitmap: The 16-bit ``displayio.Bitmap`` holding the frame.
        colors: 256 pre-swapped RGB565 values, one per palette index.
        tools: The ``bitmaptools`` module.
        font: The ``terminalio.FONT`` built-in font.
        scratch: A 16-bit bitmap the size of one built-in glyph.
    """

    def __init__(self, bitmap: object, colors: object, tools: object,
                 font: object, scratch: object) -> None:
        self._bitmap = bitmap
        self._colors = colors
        self._tools = tools
        self._font = font
        self._scratch = scratch
        self.width = bitmap.width
        self.height = bitmap.height
        self._glyph_width = scratch.width
        self._glyph_height = scratch.height

    def fill(self, index: int) -> None:
        self._tools.fill_region(self._bitmap, 0, 0, self.width, self.height,
                                self._colors[index])

    def fill_rect(self, x: int, y: int, width: int, height: int,  # noqa: CHU001 - framebuf's own names
                  index: int) -> None:
        left = x if x > 0 else 0
        top = y if y > 0 else 0
        right = x + width
        bottom = y + height
        if right > self.width:
            right = self.width
        if bottom > self.height:
            bottom = self.height
        if left < right and top < bottom:
            self._tools.fill_region(self._bitmap, left, top, right, bottom,
                                    self._colors[index])

    def rect(self, x: int, y: int, width: int, height: int, index: int,  # noqa: CHU001 - framebuf's own names
             fill: bool = False) -> None:
        if fill:
            self.fill_rect(x, y, width, height, index)
            return
        self.fill_rect(x, y, width, 1, index)
        self.fill_rect(x, y + height - 1, width, 1, index)
        self.fill_rect(x, y, 1, height, index)
        self.fill_rect(x + width - 1, y, 1, height, index)

    def hline(self, x: int, y: int, width: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.fill_rect(x, y, width, 1, index)

    def vline(self, x: int, y: int, height: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.fill_rect(x, y, 1, height, index)

    def pixel(self, x: int, y: int, index: int | None = None) -> int | None:  # noqa: CHU001 - framebuf's own names
        """Set one pixel, or with ``index`` omitted return the index drawn there."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        if index is not None:
            self._bitmap[x, y] = self._colors[index]
            return None
        value = self._bitmap[x, y]
        colors = self._colors
        for candidate in range(_PALETTE_SIZE):
            if colors[candidate] == value:
                return candidate
        return None

    def line(self, x1: int, y1: int, x2: int, y2: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        self._tools.draw_line(self._bitmap, x1, y1, x2, y2, self._colors[index])

    def ellipse(self, x: int, y: int, x_radius: int, y_radius: int,  # noqa: CHU001 - framebuf's own names
                index: int, fill: bool = False) -> None:
        """Draw a circle outline; the one ellipse ``bitmaptools`` has a C path for."""
        if x_radius != y_radius or fill:
            raise ValueError("only an unfilled circle draws at C speed on CircuitPython")
        self._tools.draw_circle(self._bitmap, x, y, x_radius, self._colors[index])

    def poly(self, x: int, y: int, coords: object, index: int,  # noqa: CHU001 - framebuf's own names
             fill: bool = False) -> None:
        """Draw a closed outline through ``coords``, an array of x, y pairs offset by (x, y)."""
        if fill:
            raise ValueError("only a polygon outline draws at C speed on CircuitPython")
        count = len(coords) // 2
        xs = array.array("h", bytes(count * 2))
        ys = array.array("h", bytes(count * 2))
        for point in range(count):
            xs[point] = x + coords[2 * point]
            ys[point] = y + coords[2 * point + 1]
        self._tools.draw_polygon(self._bitmap, xs, ys, self._colors[index])

    def blit(self, source: object, x: int, y: int, key: int = -1) -> None:  # noqa: CHU001 - framebuf's own names
        """Copy another canvas or 16-bit bitmap in, skipping pixels of index ``key``."""
        bitmap = source._bitmap if isinstance(source, BitmapCanvas) else source
        skip = None if key < 0 else self._colors[key]
        left = x
        top = y
        source_x = 0
        source_y = 0
        if left < 0:
            source_x = -left
            left = 0
        if top < 0:
            source_y = -top
            top = 0
        if (left >= self.width or top >= self.height
                or source_x >= bitmap.width or source_y >= bitmap.height):
            return
        self._tools.blit(self._bitmap, bitmap, left, top, x1=source_x, y1=source_y,
                         x2=bitmap.width, y2=bitmap.height,
                         skip_source_index=skip)

    def text(self, string: str, x: int, y: int, index: int = 1) -> None:  # noqa: CHU001 - framebuf's own names
        """Draw ``string`` in the built-in font with its top-left at (x, y)."""
        font = self._font
        glyph_width = self._glyph_width
        glyph_height = self._glyph_height
        tiles_per_row = font.bitmap.width // glyph_width
        cursor = x
        for character in string:
            glyph = font.get_glyph(ord(character))
            if glyph is not None:
                self.blit_bits(glyph.bitmap,
                               (glyph.tile_index % tiles_per_row) * glyph_width,
                               (glyph.tile_index // tiles_per_row) * glyph_height,
                               glyph_width, glyph_height, cursor, y, index,
                               self._scratch)
            cursor += glyph_width

    def blit_bits(self, sheet: object, sheet_x: int, sheet_y: int, width: int,
                  height: int, x: int, y: int, index: int, scratch: object) -> None:  # noqa: CHU001 - framebuf's own names
        """Draw the set bits of a region of a 1-bit bitmap at (x, y) in palette index ``index``.

        The region is ``width`` by ``height`` pixels of ``sheet`` from
        (sheet_x, sheet_y).  Clear bits leave the frame untouched, and
        the region clips at the frame edges.  ``scratch`` is a 16-bit
        bitmap at least the region's size; the bits are copied into it,
        the set bits recolored there, and the result blitted into the
        frame with the clear bits skipped, three ``bitmaptools`` calls
        with no Python per pixel.  Black text costs one more pass,
        since black is the value the clear bits already hold.

        Args:
            sheet: A ``displayio.Bitmap`` with two values per pixel.
            sheet_x: Left column of the region in ``sheet``.
            sheet_y: Top row of the region in ``sheet``.
            width: Region width in pixels.
            height: Region height in pixels.
            x: Frame column the region's left edge lands on.
            y: Frame row the region's top edge lands on.
            index: Palette index the set bits draw in.
            scratch: A 16-bit ``displayio.Bitmap`` at least ``width`` by
                ``height``.
        """
        if x >= self.width or y >= self.height or x + width <= 0 or y + height <= 0:
            return
        value = self._colors[index]
        tools = self._tools
        tools.blit(scratch, sheet, 0, 0, x1=sheet_x, y1=sheet_y,
                   x2=sheet_x + width, y2=sheet_y + height)
        # The copied bits are 0 and 1.  The final blit skips the clear
        # bits' value, so that value must differ from the text's.
        if value == 0:
            background = 0xFFFF
            tools.replace_color(scratch, 0, background)
            tools.replace_color(scratch, 1, value)
        else:
            background = 0
            if value != 1:
                tools.replace_color(scratch, 1, value)
        left = x if x > 0 else 0
        top = y if y > 0 else 0
        tools.blit(self._bitmap, scratch, left, top, x1=left - x, y1=top - y,
                   x2=width, y2=height, skip_source_index=background)
