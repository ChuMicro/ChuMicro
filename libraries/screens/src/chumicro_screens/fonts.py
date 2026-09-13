"""``Font``: proportional text for ``Text`` items from a font-to-py module.

A font module is what ``font_to_py -x`` writes from a TrueType or
OpenType file: every glyph as a horizontally mapped 1-bit bitmap, one
row per ``(width + 7) // 8`` bytes, behind ``height()``,
``baseline()``, ``max_width()``, ``min_ch()``, ``max_ch()``, and
``get_ch(character)``, which returns the glyph's buffer, height, and
width.  A ``Text`` item built with a ``Font`` lays its string out at
the same pixels on both device runtimes, so an app centers a label
once with ``font.width()``.

Convert a font on the host and ship the module beside the app::

    pip install font_to_py
    font_to_py -x DejaVuSans.ttf 20 sans20.py

Each runtime blits glyphs in C.  On MicroPython a glyph goes straight
from the module's read-only buffer into the strip through a two-entry
palette in the strip's own pixel format, since ``FrameBuffer.blit``
accepts a ``(buffer, width, height, format)`` source and a palette in
the destination's format.  On CircuitPython the glyphs are loaded once
at construction into a 1-bit ``displayio.Bitmap`` sheet, each through
``bitmaptools.readinto`` and one blit, and a string is rendered from
the sheet into a sprite in the strip's format once per change.
"""

import array

try:
    import framebuf
except ImportError:
    framebuf = None
    _VALUE_MASKS = None
else:
    # The largest pixel value each format holds, so the transparent
    # entry can be any other value the strip can store.
    _VALUE_MASKS = {
        framebuf.MONO_VLSB: 1,
        framebuf.MONO_HLSB: 1,
        framebuf.MONO_HMSB: 1,
        framebuf.GS8: 0xFF,
        framebuf.RGB565: 0xFFFF,
    }


class Font:
    """A font-to-py module a ``Text`` item draws in.

    ``width(string)`` returns the pixels a string spans, so a label
    centers as ``x = (screen.width - font.width(label)) // 2`` on either
    runtime.  Characters outside the module's range draw as the glyph
    the module substitutes for them, ``?`` unless the module was
    converted with another.

    RAM: on MicroPython the font costs its module plus a few hundred
    bytes; on CircuitPython the sheet adds ``height`` rows of the glyph
    widths summed, in bits, about 3 KB for a 20-pixel ASCII font, and
    each ``Text`` item holds a sprite of its string in the strip's
    format.  A Pi Pico W draws a 7-glyph word in a 20-pixel font in
    about 4 ms on MicroPython, allocating 80 bytes a glyph inside the
    module's ``get_ch``, so a strip that crosses such a label pays that
    on every paint; on CircuitPython the sprite renders once per change
    and blits in one call per strip.

    Args:
        module: A font-to-py module converted with ``-x`` (horizontal
            mapping).  A vertically mapped module raises ``ValueError``.
    """

    def __init__(self, module: object) -> None:
        if not module.hmap():
            raise ValueError("font must be horizontally mapped: convert it with font_to_py -x")
        self.height = module.height()
        self.baseline = module.baseline()
        self.max_width = module.max_width()
        self._min_ch = module.min_ch()
        self._max_ch = module.max_ch()
        get_ch = module.get_ch
        # Slot 0 holds the glyph the module substitutes for a character
        # outside its range; slot n holds the character min_ch + n - 1.
        count = self._max_ch - self._min_ch + 2
        widths = array.array("H", bytes(count * 2))
        for slot in range(count):
            widths[slot] = get_ch(self._slot_character(slot))[2]
        self._widths = widths
        if framebuf is None:
            self._sheet = None
            self._build_sheet(get_ch, module.reverse())
        else:
            self._get_ch = get_ch
            # The list is the (buffer, width, height, format) source
            # FrameBuffer.blit reads; each glyph fills its first two slots.
            self._source = [None, 0, self.height,
                            framebuf.MONO_HMSB if module.reverse() else framebuf.MONO_HLSB]
            # The two-entry palette is built for the first strip drawn
            # on, in that strip's format, and again if the format changes.
            self._palette = None
            self._palette_format = None
            self._palette_mask = 0
            self._sheet = None

    def _slot_character(self, slot: int) -> str:
        """Return the character glyph slot ``slot`` holds; slot 0 is any out-of-range one."""
        if slot == 0:
            return chr(self._max_ch + 1)
        return chr(self._min_ch + slot - 1)

    def _slot(self, ordinal: int) -> int:
        """Return the glyph slot for code point ``ordinal``, 0 when the module lacks it."""
        if self._min_ch <= ordinal <= self._max_ch:
            return ordinal - self._min_ch + 1
        return 0

    def _build_sheet(self, get_ch: object, reverse: bool) -> None:
        """Load every glyph into one 1-bit ``displayio.Bitmap``, side by side.

        Each glyph's packed rows are read into a stamp bitmap of its own
        width by ``bitmaptools.readinto`` and blitted into the sheet, so
        the build is a handful of C calls per glyph and no Python per
        byte.
        """
        import io

        import bitmaptools
        import displayio

        height = self.height
        widths = self._widths
        count = len(widths)
        sheet_x = array.array("H", bytes(count * 2))
        column = 0
        for slot in range(count):
            sheet_x[slot] = column
            column += widths[slot]
        sheet = displayio.Bitmap(column, height, 2)
        first_pixel_high = not reverse
        for slot in range(count):
            width = widths[slot]
            if width:
                stamp = displayio.Bitmap(width, height, 2)
                bitmaptools.readinto(stamp, io.BytesIO(get_ch(self._slot_character(slot))[0]),
                                     1, element_size=1,
                                     reverse_pixels_in_element=first_pixel_high)
                bitmaptools.blit(sheet, stamp, sheet_x[slot], 0)
        self._sheet = sheet
        self._sheet_x = sheet_x

    def width(self, string: str) -> int:
        """Return the pixels ``string`` spans when drawn, the sum of its glyph widths.

        Args:
            string: The text to measure.
        """
        widths = self._widths
        total = 0
        for character in string:
            total += widths[self._slot(ord(character))]
        return total

    def draw(self, framebuffer: object, pixel_format: int, string: str, x: int, y: int,  # noqa: CHU001 - framebuf's own names
             value: int) -> None:
        """Blit ``string`` into a ``framebuf.FrameBuffer`` in pixel value ``value``, top-left at (x, y).

        Each glyph goes from the module's buffer through a two-pixel
        palette ``FrameBuffer`` in ``pixel_format``, since framebuf
        reads a palette in the destination's format; the transparent
        entry is any other value the format holds, and the blit's key
        is that value after the lookup.  Text clips at the buffer's
        edges.

        Args:
            framebuffer: The strip's ``FrameBuffer``.
            pixel_format: The framebuf format it was built with.
            string: The text to draw.
            x: Column of the first glyph's left edge.
            y: Row of the glyphs' top edge, in the buffer's rows.
            value: The pixel value to draw in.
        """
        palette = self._palette
        if pixel_format != self._palette_format:
            palette = self._palette = framebuf.FrameBuffer(bytearray(4), 2, 1, pixel_format)
            self._palette_format = pixel_format
            self._palette_mask = _VALUE_MASKS[pixel_format]
        background = (value + 1) & self._palette_mask
        palette.pixel(0, 0, background)
        palette.pixel(1, 0, value)
        source = self._source
        get_ch = self._get_ch
        cursor = x
        for character in string:
            glyph, _height, width = get_ch(character)
            if width:
                source[0] = glyph
                source[1] = width
                framebuffer.blit(source, cursor, y, background, palette)
            cursor += width

    def render(self, string: str, value: int, values: int, key: int) -> object:
        """Return a ``displayio.Bitmap`` of ``string`` in ``value`` over ``key``, the sprite a strip blits.

        Each glyph's sheet region is stamped into the sprite through a
        scratch bitmap, three ``bitmaptools`` calls per glyph and no
        Python per pixel.

        Args:
            string: The text to render.
            value: The pixel value the glyphs' set bits take.
            values: Distinct values per pixel of the strip's format,
                65536 for a 16-bit strip.
            key: The value the sprite's background holds, which the
                strip skips when it blits; any value other than
                ``value``.
        """
        import bitmaptools
        import displayio

        from chumicro_screens.bitmap_strip import stamp_glyph

        sheet = self._sheet
        sheet_x = self._sheet_x
        widths = self._widths
        height = self.height
        sprite = displayio.Bitmap(self.width(string), height, values)
        if key:
            bitmaptools.fill_region(sprite, 0, 0, sprite.width, height, key)
        scratch = displayio.Bitmap(self.max_width, height, values)
        cursor = 0
        for character in string:
            slot = self._slot(ord(character))
            width = widths[slot]
            if width:
                stamp_glyph(sprite, scratch, sheet, sheet_x[slot], 0, width, height,
                            cursor, value, key)
            cursor += width
        return sprite
