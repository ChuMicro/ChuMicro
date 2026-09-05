"""``sys.modules`` stubs for driving the CircuitPython frame backend on CPython.

``displayio.Bitmap`` is a ``bytearray`` subclass here so ``memoryview``
works on it the way the firmware's buffer protocol does, with 2D item
access on top; ``bitmaptools`` reimplements the five primitives the
canvas maps to with the firmware's own validation (``fill_region`` and
``blit`` refuse out-of-range coordinates, everything else clips through
the pixel writer); ``terminalio.FONT`` is a synthetic monospace sheet
whose every glyph is a filled block one pixel in from its tile edge, so
tests can assert placement and color without a real font.

CPython only: ``bytearray`` subclassing with ``__new__`` is what the
unix ports lack, which is why the file that imports this is marked
``("cpython",)``.
"""

__chumicro_test_support__ = True


class DisplayioStub:
    """Stand-in for ``displayio``: a ``Bitmap`` that is a buffer and a 2D array."""

    class Bitmap(bytearray):
        def __new__(cls, width, height, value_count):
            return bytearray.__new__(cls)

        def __init__(self, width, height, value_count):
            bytearray.__init__(self, width * height * (2 if value_count > 256 else 1))
            self.width = width
            self.height = height
            self.value_count = value_count
            self.bytes_per_value = 2 if value_count > 256 else 1
            self.bits_per_value = 16 if value_count > 256 else (8 if value_count > 2 else 1)

        def _offset(self, x, y):  # noqa: CHU001 - the firmware's own names
            if not (0 <= x < self.width and 0 <= y < self.height):
                raise IndexError("pixel out of range")
            return (y * self.width + x) * self.bytes_per_value

        def __getitem__(self, key):
            if isinstance(key, tuple):
                offset = self._offset(*key)
                value = bytearray.__getitem__(self, offset)
                if self.bytes_per_value == 2:
                    value |= bytearray.__getitem__(self, offset + 1) << 8
                return value
            return bytearray.__getitem__(self, key)

        def __setitem__(self, key, value):
            if isinstance(key, tuple):
                offset = self._offset(*key)
                bytearray.__setitem__(self, offset, value & 0xFF)
                if self.bytes_per_value == 2:
                    bytearray.__setitem__(self, offset + 1, value >> 8)
                return
            bytearray.__setitem__(self, key, value)

        def write_pixel(self, x, y, value):  # noqa: CHU001 - the firmware's own names
            """The firmware's bounds-checked writer: out-of-range writes are dropped."""
            if 0 <= x < self.width and 0 <= y < self.height:
                self[x, y] = value


class BitmaptoolsStub:
    """Stand-in for ``bitmaptools`` with the firmware's validation and clipping."""

    @staticmethod
    def _validate_range(x1, y1, x2, y2, width, height):  # noqa: CHU001 - the firmware's own names
        if not (0 <= x1 <= width and x1 <= x2 <= width):
            raise ValueError("x out of range")
        if not (0 <= y1 <= height and y1 <= y2 <= height):
            raise ValueError("y out of range")

    @staticmethod
    def fill_region(bitmap, x1, y1, x2, y2, value):  # noqa: CHU001 - the firmware's own names
        BitmaptoolsStub._validate_range(x1, y1, x2, y2, bitmap.width, bitmap.height)
        for y in range(y1, y2):
            for x in range(x1, x2):
                bitmap[x, y] = value

    @staticmethod
    def draw_line(bitmap, x1, y1, x2, y2, value):  # noqa: CHU001 - the firmware's own names
        dx = abs(x2 - x1)
        dy = -abs(y2 - y1)
        step_x = 1 if x1 < x2 else -1
        step_y = 1 if y1 < y2 else -1
        error = dx + dy
        while True:
            bitmap.write_pixel(x1, y1, value)
            if x1 == x2 and y1 == y2:
                return
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x1 += step_x
            if doubled <= dx:
                error += dx
                y1 += step_y

    @staticmethod
    def draw_circle(bitmap, x, y, radius, value):  # noqa: CHU001 - the firmware's own names
        center_x = min(max(x, 0), bitmap.width)
        center_y = min(max(y, 0), bitmap.height)
        offset_y = radius
        decision = 3 - 2 * radius
        offset_x = 0
        while offset_x <= offset_y:
            for point_x, point_y in ((offset_x, offset_y), (-offset_x, -offset_y),
                                     (-offset_x, offset_y), (offset_x, -offset_y),
                                     (offset_y, offset_x), (-offset_y, offset_x),
                                     (-offset_y, -offset_x), (offset_y, -offset_x)):
                bitmap.write_pixel(center_x + point_x, center_y + point_y, value)
            if decision <= 0:
                decision += 4 * offset_x + 6
            else:
                decision += 4 * (offset_x - offset_y) + 10
                offset_y -= 1
            offset_x += 1

    @staticmethod
    def draw_polygon(bitmap, xs, ys, value, close=True):
        count = len(xs)
        for point in range(count - 1):
            BitmaptoolsStub.draw_line(bitmap, xs[point], ys[point],
                                      xs[point + 1], ys[point + 1], value)
        if close and count > 1:
            BitmaptoolsStub.draw_line(bitmap, xs[-1], ys[-1], xs[0], ys[0], value)

    @staticmethod
    def blit(dest, source, x, y, *, x1=0, y1=0, x2=None, y2=None,  # noqa: CHU001 - the firmware's own names
             skip_source_index=None, skip_dest_index=None):
        if not (0 <= x <= dest.width and 0 <= y <= dest.height):
            raise ValueError("x or y out of range")
        if x2 is None:
            x2 = source.width
        if y2 is None:
            y2 = source.height
        BitmaptoolsStub._validate_range(x1, y1, x2, y2, source.width, source.height)
        if dest.bits_per_value < source.bits_per_value:
            raise ValueError("source palette too large")
        for column in range(x2 - x1):
            for row in range(y2 - y1):
                value = source[x1 + column, y1 + row]
                if skip_source_index is not None and value == skip_source_index:
                    continue
                dest_x = x + column
                dest_y = y + row
                if not (dest_x < dest.width and dest_y < dest.height):
                    continue
                if skip_dest_index is not None and dest[dest_x, dest_y] == skip_dest_index:
                    continue
                dest[dest_x, dest_y] = value

    @staticmethod
    def replace_color(bitmap, old_color, new_color):
        for y in range(bitmap.height):
            for x in range(bitmap.width):
                if bitmap[x, y] == old_color:
                    bitmap[x, y] = new_color

    @staticmethod
    def readinto(bitmap, file, bits_per_pixel, element_size=1,
                 reverse_pixels_in_element=False, swap_bytes_in_element=False,
                 reverse_rows=False):
        """Fill ``bitmap`` row by row from packed pixels read off ``file``.

        Models the one shape the canvas reads, one bit per pixel in
        single bytes; ``reverse_pixels_in_element`` puts the row's first
        pixel in the most significant bit, as the firmware does.
        """
        if bits_per_pixel != 1 or element_size != 1 or swap_bytes_in_element:
            raise ValueError("the stub reads 1-bit pixels in single bytes only")
        row_size = (bitmap.width + 7) // 8
        for y in range(bitmap.height):
            row = file.read(row_size)
            if len(row) != row_size:
                raise EOFError
            target_y = bitmap.height - 1 - y if reverse_rows else y
            for x in range(bitmap.width):
                bit = 7 - (x & 7) if reverse_pixels_in_element else x & 7
                bitmap[x, target_y] = (row[x >> 3] >> bit) & 1


class _Glyph:
    def __init__(self, bitmap, tile_index, width, height):
        self.bitmap = bitmap
        self.tile_index = tile_index
        self.width = width
        self.height = height
        self.dx = 0
        self.dy = 0
        self.shift_x = width
        self.shift_y = 0


class _Font:
    """A synthetic monospace font: printable ASCII in one row of tiles.

    Every glyph is a filled block one pixel in from its tile edge, so a
    drawn character covers ``(x + 1, y + 1)`` to ``(x + width - 2,
    y + height - 2)`` and leaves the tile's border untouched.
    """

    GLYPH_WIDTH = 6
    GLYPH_HEIGHT = 12
    FIRST = 0x20
    LAST = 0x7E

    def __init__(self):
        count = self.LAST - self.FIRST + 1
        self.bitmap = DisplayioStub.Bitmap(self.GLYPH_WIDTH * count, self.GLYPH_HEIGHT, 2)
        for tile in range(count):
            left = tile * self.GLYPH_WIDTH
            for y in range(1, self.GLYPH_HEIGHT - 1):
                for x in range(1, self.GLYPH_WIDTH - 1):
                    self.bitmap[left + x, y] = 1

    def get_bounding_box(self):
        return (self.GLYPH_WIDTH, self.GLYPH_HEIGHT)

    def get_glyph(self, codepoint):
        if not self.FIRST <= codepoint <= self.LAST:
            return None
        return _Glyph(self.bitmap, codepoint - self.FIRST,
                      self.GLYPH_WIDTH, self.GLYPH_HEIGHT)


class TerminalioStub:
    """Stand-in for ``terminalio`` carrying the synthetic ``FONT``."""

    def __init__(self):
        self.FONT = _Font()
