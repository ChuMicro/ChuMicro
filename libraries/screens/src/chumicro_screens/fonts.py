"""``Font``: proportional text on the portable canvas from a font-to-py module.

A font module is what ``font_to_py -x`` writes from a TrueType or
OpenType file: every glyph as a horizontally mapped 1-bit bitmap, one
row per ``(width + 7) // 8`` bytes, behind ``height()``,
``baseline()``, ``max_width()``, ``min_ch()``, ``max_ch()``, and
``get_ch(character)``, which returns the glyph's buffer, height, and
width.  ``Font`` draws such a module on the canvas in a palette index
with one call shape on both device runtimes, and lays text out at the
same pixels on both, so an app centers a label once.

Convert a font on the host and ship the module beside the app::

    pip install font_to_py
    font_to_py -x DejaVuSans.ttf 20 sans20.py

Each runtime blits glyphs in C.  On MicroPython a glyph goes straight
from the module's read-only buffer through a two-entry palette, since
``FrameBuffer.blit`` accepts a ``(buffer, width, height, format)``
source.  On CircuitPython the glyphs are loaded once at construction
into a 1-bit ``displayio.Bitmap`` sheet, each through
``bitmaptools.readinto`` and one blit, and ``bitmaptools`` draws from
the sheet through a scratch bitmap.
"""

import array

try:
    import framebuf
except ImportError:
    framebuf = None


class Font:
    """A font-to-py module drawn on the portable canvas in a palette index.

    ``text(canvas, string, x, y, index)`` draws with the top-left of the
    first glyph at (x, y), and ``width(string)`` returns the pixels a
    string spans, so a label centers as ``x = (canvas.width -
    font.width(label)) // 2`` on either runtime.  Characters outside
    the module's range draw as the glyph the module substitutes for
    them, ``?`` unless the module was converted with another.

    RAM: on MicroPython the font costs its module plus a few hundred
    bytes; on CircuitPython the sheet adds ``height`` rows of the glyph
    widths summed, in bits, about 3 KB for a 20-pixel ASCII font, plus
    a 16-bit scratch bitmap of the widest glyph.  Import the module and
    construct ``Font`` after the panel: the panel's frame wants the
    heap's largest free block, and on a Pi Pico W under CircuitPython
    the 115,200-byte frame no longer fits once a font module has been
    compiled ahead of it.

    ``text`` targets the indexed canvas, ``GC9A01AIndexed.frame``: on
    MicroPython the palette it blits through is built for an 8-bit
    frame, so a 16-bit ``GC9A01A.frame`` or the mono OLED frame renders
    wrong.  A Pi Pico W draws a 7-glyph word in a 20-pixel font in
    4.0 ms on MicroPython, allocating 80 bytes a glyph inside the
    module's ``get_ch``, and in 7.4 ms on CircuitPython allocating
    nothing, so ``text`` is redraw work rather than something to call
    on every tick.

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
            self._palette_buffer = bytearray(2)
            self._palette = framebuf.FrameBuffer(self._palette_buffer, 2, 1, framebuf.GS8)
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
        self._scratch = displayio.Bitmap(self.max_width, height, 65536)

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

    def text(self, canvas: object, string: str, x: int, y: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        """Draw ``string`` on ``canvas`` in palette index ``index``, top-left at (x, y).

        Only the glyphs' set pixels are drawn; the canvas shows through
        the rest.  Text clips at the canvas edges.

        Args:
            canvas: ``GC9A01AIndexed.frame`` on either runtime.
            string: The text to draw.
            x: Column of the first glyph's left edge.
            y: Row of the glyphs' top edge.
            index: Palette index to draw in.
        """
        if self._sheet is None:
            self._text_framebuf(canvas, string, x, y, index)
        else:
            self._text_bitmap(canvas, string, x, y, index)

    def _text_framebuf(self, canvas: object, string: str, x: int, y: int,  # noqa: CHU001 - framebuf's own names
                       index: int) -> None:
        """Blit each glyph from the module's buffer through a palette of ``index`` over a skipped key."""
        background = (index + 1) & 0xFF
        palette_buffer = self._palette_buffer
        palette_buffer[0] = background
        palette_buffer[1] = index
        palette = self._palette
        source = self._source
        get_ch = self._get_ch
        cursor = x
        for character in string:
            glyph, _height, width = get_ch(character)
            if width:
                source[0] = glyph
                source[1] = width
                canvas.blit(source, cursor, y, background, palette)
            cursor += width

    def _text_bitmap(self, canvas: object, string: str, x: int, y: int,  # noqa: CHU001 - framebuf's own names
                     index: int) -> None:
        """Blit each glyph's sheet region through the canvas's 1-bit path."""
        sheet = self._sheet
        sheet_x = self._sheet_x
        widths = self._widths
        scratch = self._scratch
        height = self.height
        cursor = x
        for character in string:
            slot = self._slot(ord(character))
            width = widths[slot]
            if width:
                canvas.blit_bits(sheet, sheet_x[slot], 0, width, height,
                                 cursor, y, index, scratch)
            cursor += width
