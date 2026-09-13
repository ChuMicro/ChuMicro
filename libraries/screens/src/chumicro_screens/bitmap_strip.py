"""``BitmapStrip``: the CircuitPython strip canvas, a ``displayio.Bitmap`` a few rows tall.

The strip holds ``width`` by ``rows`` pixels in the panel's format and
paints the ``Screen`` items into it through ``bitmaptools`` with
``top`` as the panel row its row 0 holds; the panel streams the
bitmap's buffer over the bus.  ``bitmaptools`` costs about 120 us a
call on an RP2040, so every primitive here is one call per strip, and
the two that cannot be are reshaped once and cached on the item: text
renders into a sprite the strip blits, and a ring becomes the arcs of
a polygon that cross each strip band, one ``draw_polygon`` each, since
``bitmaptools.draw_circle`` moves a center that lies outside the
bitmap instead of clipping.
"""

__chumicro_runtimes__ = ("circuitpython",)

import array
import math

import bitmaptools
import displayio
import terminalio

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

# A ring's polygon has one vertex per pixel of radius within these
# bounds, which keeps every chord within a quarter pixel of the circle.
_MIN_VERTICES = const(12)
_MAX_VERTICES = const(64)


def stamp_glyph(sprite: object, scratch: object, sheet: object, sheet_x: int, sheet_y: int,
                width: int, height: int, x: int, value: int, key: int) -> None:  # noqa: CHU001 - framebuf's own names
    """Copy one 1-bit glyph from ``sheet`` into ``sprite`` at column ``x`` in ``value``.

    The glyph's set bits take ``value`` and its clear bits leave the
    sprite untouched: the region is copied into ``scratch`` as 0 and 1,
    recolored there, and blitted with the clear bits' value skipped.
    That value must differ from the text's, so a text value of 0 first
    moves the clear bits to ``key``, the sprite's own background.

    Args:
        sprite: The destination bitmap.
        scratch: A bitmap at least ``width`` by ``height`` in the
            sprite's format.
        sheet: A 1-bit bitmap holding the glyph.
        sheet_x: Left column of the glyph in ``sheet``.
        sheet_y: Top row of the glyph in ``sheet``.
        width: Glyph width in pixels.
        height: Glyph height in pixels.
        x: Sprite column the glyph's left edge lands on.
        value: The pixel value the set bits take.
        key: The sprite's background value, never equal to ``value``.
    """
    bitmaptools.blit(scratch, sheet, 0, 0, x1=sheet_x, y1=sheet_y,
                     x2=sheet_x + width, y2=sheet_y + height)
    if value == 0:
        skip = key
        bitmaptools.replace_color(scratch, 0, key)
        bitmaptools.replace_color(scratch, 1, 0)
    else:
        skip = 0
        if value != 1:
            bitmaptools.replace_color(scratch, 1, value)
    bitmaptools.blit(sprite, scratch, x, 0, x1=0, y1=0, x2=width, y2=height,
                     skip_source_index=skip)


class BitmapStrip:
    """``width`` by ``rows`` pixels of the panel, drawn through bitmaptools.

    Args:
        width: Strip width in pixels, the panel's width.
        rows: Strip height in pixels; a flush paints the panel in bands
            this tall.
        values: Distinct values per pixel of the panel's format, 65536
            for a 16-bit panel.
    """

    def __init__(self, width: int, rows: int, values: int = 65536) -> None:
        self.width = width
        self.rows = rows
        self.values = values
        self.top = 0
        self.bitmap = displayio.Bitmap(width, rows, values)
        self.buffer = memoryview(self.bitmap)
        font = terminalio.FONT
        self.glyph_width, self.glyph_height = font.get_bounding_box()
        self._tiles_per_row = font.bitmap.width // self.glyph_width
        self._scratch = displayio.Bitmap(self.glyph_width, self.glyph_height, values)

    def window(self, left: int, right: int) -> None:
        """Nothing to lay out: the strip paints full width and the panel bounds each row it sends."""

    def clear(self, value: int) -> None:
        self.bitmap.fill(value)

    def _fill(self, left: int, top: int, right: int, bottom: int, value: int) -> None:
        """Fill the rectangle clipped to the strip; ``fill_region`` refuses coordinates past the edge."""
        if left < 0:
            left = 0
        if top < 0:
            top = 0
        if right > self.width:
            right = self.width
        if bottom > self.rows:
            bottom = self.rows
        if right > left and bottom > top:
            bitmaptools.fill_region(self.bitmap, left, top, right, bottom, value)

    def fill_rect(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        y -= self.top  # noqa: CHU001 - framebuf's own names
        self._fill(x, y, x + width, y + height, value)

    def box(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        y -= self.top  # noqa: CHU001 - framebuf's own names
        fill = self._fill
        fill(x, y, x + width, y + 1, value)
        fill(x, y + height - 1, x + width, y + height, value)
        fill(x, y, x + 1, y + height, value)
        fill(x + width - 1, y, x + width, y + height, value)

    def line(self, x0: int, y0: int, x1: int, y1: int, value: int) -> None:
        top = self.top
        bitmaptools.draw_line(self.bitmap, x0, y0 - top, x1, y1 - top, value)

    def prepare_ring(self, x_center: int, y_center: int, radius: int, cache: dict) -> None:
        """Cut the ring's polygon into per-band arcs in ``cache`` unless it already holds them.

        ``cache[None]`` records the geometry the arcs were cut for; each
        strip band then holds, under its index, the runs of consecutive
        vertices whose edges cross it, as pre-shifted coordinate arrays
        ``draw_polygon`` takes.  Cutting walks the vertices once and
        costs a few milliseconds for a large ring, paid when the item is
        added or moved rather than inside a flush.
        """
        rows = self.rows
        key = (x_center, y_center, radius, rows)
        if cache.get(None) == key:
            return
        cache.clear()
        cache[None] = key
        _cut_arcs(cache, x_center, y_center, radius, rows)

    def ring(self, x_center: int, y_center: int, radius: int, value: int,
             cache: dict) -> None:
        arcs = cache.get(self.top // self.rows)
        if arcs is not None:
            bitmap = self.bitmap
            for xs, ys in arcs:
                bitmaptools.draw_polygon(bitmap, xs, ys, value, close=False)

    def prepare_text(self, string: str, value: int, font: object | None, cache: list) -> None:
        """Render ``string`` into the sprite ``cache`` holds unless it already shows this text.

        ``cache`` is the item's ``[key, sprite]`` pair; the key records
        the string, value, and font the sprite was rendered from, so a
        mark that changed none of them costs nothing here, and one that
        did pays the render at mark time rather than inside a flush.
        """
        key = (string, value, font)
        if cache[0] != key:
            cache[1] = self._render(string, value, font)
            cache[0] = key

    def text(self, string: str, x: int, y: int, value: int, font: object | None,  # noqa: CHU001 - framebuf's own names
             cache: list) -> None:
        self.blit(cache[1], x, y, self.values - 1 if value == 0 else 0)

    def _render(self, string: str, value: int, font: object | None) -> object:
        """Return a sprite of ``string`` in ``value`` over a transparent background."""
        key = self.values - 1 if value == 0 else 0
        if font is not None:
            return font.render(string, value, self.values, key)
        glyph_width = self.glyph_width
        glyph_height = self.glyph_height
        terminal_font = terminalio.FONT
        sheet = terminal_font.bitmap
        tiles_per_row = self._tiles_per_row
        scratch = self._scratch
        sprite = displayio.Bitmap(glyph_width * len(string), glyph_height, self.values)
        if key:
            bitmaptools.fill_region(sprite, 0, 0, sprite.width, glyph_height, key)
        cursor = 0
        for character in string:
            glyph = terminal_font.get_glyph(ord(character))
            if glyph is not None:
                stamp_glyph(sprite, scratch, sheet,
                            (glyph.tile_index % tiles_per_row) * glyph_width,
                            (glyph.tile_index // tiles_per_row) * glyph_height,
                            glyph_width, glyph_height, cursor, value, key)
            cursor += glyph_width
        return sprite

    def blit(self, source: object, x: int, y: int, key: int) -> None:  # noqa: CHU001 - framebuf's own names
        """Blit ``source`` with its top-left at panel (x, y), skipping ``key``, clipped to the strip."""
        y -= self.top  # noqa: CHU001 - framebuf's own names
        rows = self.rows
        width = self.width
        source_width = source.width
        source_height = source.height
        if x >= width or y >= rows or x + source_width <= 0 or y + source_height <= 0:
            return
        left = 0
        top = 0
        if x < 0:
            left = -x
            x = 0  # noqa: CHU001 - framebuf's own names
        if y < 0:
            top = -y
            y = 0  # noqa: CHU001 - framebuf's own names
        right = source_width
        if x + right - left > width:
            right = left + width - x
        bottom = source_height
        if y + bottom - top > rows:
            bottom = top + rows - y
        if key < 0:
            bitmaptools.blit(self.bitmap, source, x, y, x1=left, y1=top, x2=right, y2=bottom)
        else:
            bitmaptools.blit(self.bitmap, source, x, y, x1=left, y1=top, x2=right, y2=bottom,
                             skip_source_index=key)


def _cut_arcs(cache: dict, x_center: int, y_center: int, radius: int, rows: int) -> None:
    """Fill ``cache`` with the polyline pieces of the ring's polygon per strip band.

    Walking the edges once, each edge's two vertices join the run in progress
    for every band the edge crosses, so a band ends up with the arcs
    that cross it as ``(xs, ys)`` pairs of ``array.array('h')``, rows
    shifted so the band's first row is 0, the form
    ``bitmaptools.draw_polygon`` takes.
    """
    count = radius
    if count < _MIN_VERTICES:
        count = _MIN_VERTICES
    elif count > _MAX_VERTICES:
        count = _MAX_VERTICES
    xs = [0] * count
    ys = [0] * count
    step = 2 * math.pi / count
    for index in range(count):
        angle = step * index
        xs[index] = x_center + int(round(radius * math.cos(angle)))
        ys[index] = y_center + int(round(radius * math.sin(angle)))
    runs = {}
    for index in range(count):
        after = index + 1 if index + 1 < count else 0
        y_low = ys[index]
        y_high = ys[after]
        if y_high < y_low:
            y_low, y_high = y_high, y_low
        band = y_low // rows
        last_band = y_high // rows
        while band <= last_band:
            band_runs = runs.get(band)
            if band_runs is None:
                band_runs = runs[band] = []
            if band_runs and band_runs[-1][-1] == index:
                band_runs[-1].append(after)
            else:
                band_runs.append([index, after])
            band += 1
    for band in runs:
        band_runs = runs[band]
        # The walk started at vertex 0, so a run ending at the last
        # vertex continues into a run starting at vertex 0.
        if len(band_runs) > 1 and band_runs[-1][-1] == 0 and band_runs[0][0] == 0:
            band_runs[-1].extend(band_runs[0][1:])
            del band_runs[0]
        top = band * rows
        cache[band] = [(array.array("h", [xs[i] for i in run]),
                        array.array("h", [ys[i] - top for i in run]))
                       for run in band_runs]
