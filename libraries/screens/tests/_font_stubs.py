"""``FontModuleStub``: a font-to-py module stand-in with three hand-drawn glyphs.

The object answers the functions a module written by ``font_to_py``
exposes (``height``, ``baseline``, ``max_width``, ``hmap``,
``reverse``, ``monospaced``, ``min_ch``, ``max_ch``, ``get_ch``) over
a glyph blob laid out the same way: each glyph's rows packed most
significant bit first into ``(width + 7) // 8`` bytes, ``get_ch``
returning a memoryview slice of the blob with the height and width.
The glyphs are ``A`` (5 wide), ``B`` (9 wide, so two bytes a row), and
``C`` (3 wide), all 4 rows tall, and any other character maps to
``C`` the way a module substitutes its default glyph.

Staged next to the test files that import it; carries no runtime
marker because it never runs standalone.
"""

__chumicro_test_support__ = True

HEIGHT = 4
BASELINE = 3
FIRST = 65
LAST = 67

#: Glyph name to (width, rows), rows as bytes most significant bit first.
GLYPHS = {
    "A": (5, (0x70, 0x88, 0xF8, 0x88)),
    "B": (9, (0xFF, 0x80, 0x80, 0x80, 0xFF, 0x80, 0x80, 0x80)),
    "C": (3, (0xE0, 0x80, 0x80, 0xE0)),
}


def _reverse_bits(byte):
    """Return ``byte`` with its eight bits in the opposite order."""
    result = 0
    for _ in range(8):
        result = (result << 1) | (byte & 1)
        byte >>= 1
    return result


class FontModuleStub:
    """The font-to-py module surface over the three glyphs above.

    Args:
        hmap: What ``hmap()`` reports; the glyph data is horizontal
            regardless, so ``False`` models a module the font layer
            must refuse.
        reverse: Store each byte least significant bit first and report
            it through ``reverse()``, the ``font_to_py -r`` layout.
    """

    def __init__(self, hmap=True, reverse=False):
        self._hmap = hmap
        self._reverse = reverse
        blob = b""
        self._offsets = {}
        for character in "ABC":
            width, rows = GLYPHS[character]
            self._offsets[character] = (len(blob), width)
            if reverse:
                rows = tuple(_reverse_bits(byte) for byte in rows)
            blob += bytes(rows)
        self._view = memoryview(blob)

    def height(self):
        return HEIGHT

    def baseline(self):
        return BASELINE

    def max_width(self):
        return 9

    def hmap(self):
        return self._hmap

    def reverse(self):
        return self._reverse

    def monospaced(self):
        return False

    def min_ch(self):
        return FIRST

    def max_ch(self):
        return LAST

    def get_ch(self, character):
        """Return ``(buffer, height, width)`` for ``character``, ``C``'s for an unknown one."""
        if character not in self._offsets:
            character = "C"
        offset, width = self._offsets[character]
        length = ((width - 1) // 8 + 1) * HEIGHT
        return self._view[offset:offset + length], HEIGHT, width
