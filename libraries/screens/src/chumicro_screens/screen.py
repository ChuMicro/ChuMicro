"""``Screen``: a scene of items painted per dirty strip, with no frame in RAM.

An app builds items (``Rect``, ``Box``, ``Line``, ``Ring``, ``Text``,
``Sprite``), adds them to a ``Screen``, and mutates their attributes;
``screen.mark(item)`` records that the item changed.  ``flush()`` is
the ``ScreenService`` panel protocol: each advance paints one strip of
the panel, the rows the marked items cover, into the panel's strip
buffer through the runtime's C drawing primitives and sends it as one
bus transfer, windowed to the columns the marked items cover where
the panel takes a column window.  RAM is the strip plus the scene,
whatever the panel's size, and the panel's own memory holds the
picture.

Every item costs one C call per strip it crosses, so a strip's paint
time is the bus transfer plus those calls: on an RP2040 a framebuf
call is 60 to 370 us and a bitmaptools call costs per pixel touched,
about 0.7 us for a fill and 1.5 us for a blit.  A panel's ``rows`` is
the one knob: fewer rows per strip means less time per advance and
more advances per frame.
"""


class Item:
    """What every scene item carries: its bounds and where it was last painted.

    ``left``, ``top``, ``right``, ``bottom`` are the item's current
    bounds, right and bottom exclusive; ``layout`` recomputes them from
    the item's own attributes.  The ``shown_*`` four are the bounds the
    last flush painted, so a moved or shrunk item also repaints what it
    left behind.
    """

    left = 0
    top = 0
    right = 0
    bottom = 0
    shown_left = 0
    shown_top = 0
    shown_right = 0
    shown_bottom = 0

    def layout(self, strip: object) -> None:
        """Recompute the bounds from the item's attributes; ``strip`` supplies font metrics."""

    def draw(self, strip: object) -> None:
        """Paint the item into ``strip``, whose ``top`` is the panel row its row 0 holds."""
        raise NotImplementedError


class Rect(Item):
    """A filled rectangle.

    Args:
        x: Left column.
        y: Top row.
        width: Width in pixels.
        height: Height in pixels.
        value: The pixel value to fill with, as the panel stores it.
    """

    def __init__(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.value = value

    def layout(self, strip: object) -> None:
        self.left = self.x
        self.top = self.y
        self.right = self.x + self.width
        self.bottom = self.y + self.height

    def draw(self, strip: object) -> None:
        strip.fill_rect(self.x, self.y, self.width, self.height, self.value)


class Box(Rect):
    """A one-pixel rectangle outline with ``Rect``'s arguments."""

    def draw(self, strip: object) -> None:
        strip.box(self.x, self.y, self.width, self.height, self.value)


class Line(Item):
    """A one-pixel line between two points, both ends inclusive.

    Args:
        x0: First end's column.
        y0: First end's row.
        x1: Second end's column.
        y1: Second end's row.
        value: The pixel value to draw in.
    """

    def __init__(self, x0: int, y0: int, x1: int, y1: int, value: int) -> None:
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.value = value

    def layout(self, strip: object) -> None:
        self.left = self.x0 if self.x0 < self.x1 else self.x1
        self.right = (self.x1 if self.x0 < self.x1 else self.x0) + 1
        self.top = self.y0 if self.y0 < self.y1 else self.y1
        self.bottom = (self.y1 if self.y0 < self.y1 else self.y0) + 1

    def draw(self, strip: object) -> None:
        strip.line(self.x0, self.y0, self.x1, self.y1, self.value)


class Ring(Item):
    """A one-pixel circle outline.

    Args:
        x_center: Center column.
        y_center: Center row.
        radius: Radius in pixels.
        value: The pixel value to draw in.
    """

    def __init__(self, x_center: int, y_center: int, radius: int, value: int) -> None:
        self.x_center = x_center
        self.y_center = y_center
        self.radius = radius
        self.value = value
        # A strip canvas that cannot draw a circle across its edge keeps
        # its per-strip pieces here, keyed by strip.
        self.cache = {}

    def layout(self, strip: object) -> None:
        radius = self.radius
        self.left = self.x_center - radius
        self.top = self.y_center - radius
        self.right = self.x_center + radius + 1
        self.bottom = self.y_center + radius + 1
        strip.prepare_ring(self.x_center, self.y_center, radius, self.cache)

    def draw(self, strip: object) -> None:
        strip.ring(self.x_center, self.y_center, self.radius, self.value, self.cache)


class Text(Item):
    """A string in the panel's built-in font or a ``chumicro_screens.fonts.Font``.

    Set ``string`` (or ``value``, ``x``, ``y``) and mark the item to
    change it.  Only the glyphs' set pixels are painted; the scene
    shows through the rest.

    Args:
        x: Column of the first glyph's left edge.
        y: Row of the glyphs' top edge.
        string: The text.
        value: The pixel value to draw in.
        font: A ``Font``, or ``None`` for the runtime's built-in font,
            8 by 8 on MicroPython and ``terminalio.FONT`` on
            CircuitPython, whose metrics differ.
    """

    def __init__(self, x: int, y: int, string: str, value: int,  # noqa: CHU001 - framebuf's own names
                 font: object | None = None) -> None:
        self.x = x
        self.y = y
        self.string = string
        self.value = value
        self.font = font
        # A strip canvas that paints text from a pre-rendered sprite
        # keeps the sprite and what it was rendered from here.
        self.cache = [None, None]

    def layout(self, strip: object) -> None:
        font = self.font
        if font is None:
            width = strip.glyph_width * len(self.string)
            height = strip.glyph_height
        else:
            width = font.width(self.string)
            height = font.height
        self.left = self.x
        self.top = self.y
        self.right = self.x + width
        self.bottom = self.y + height
        strip.prepare_text(self.string, self.value, font, self.cache)

    def draw(self, strip: object) -> None:
        strip.text(self.string, self.x, self.y, self.value, self.font, self.cache)


class Sprite(Item):
    """A bitmap in the strip's own format, blitted with one value transparent.

    Args:
        x: Left column.
        y: Top row.
        source: What the runtime's strip blits: a ``framebuf.FrameBuffer``
            or a ``(buffer, width, height, format)`` sequence on
            MicroPython, a ``displayio.Bitmap`` on CircuitPython.
        width: Source width in pixels.
        height: Source height in pixels.
        key: The source value left unpainted, or ``-1`` for none.
    """

    def __init__(self, x: int, y: int, source: object, width: int, height: int,  # noqa: CHU001 - framebuf's own names
                 key: int = -1) -> None:
        self.x = x
        self.y = y
        self.source = source
        self.width = width
        self.height = height
        self.key = key

    def layout(self, strip: object) -> None:
        self.left = self.x
        self.top = self.y
        self.right = self.x + self.width
        self.bottom = self.y + self.height

    def draw(self, strip: object) -> None:
        strip.blit(self.source, self.x, self.y, self.key)


class Screen:
    """A panel's scene: items in paint order, and the rectangle the next flush paints.

    Items are painted back to front in the order added.  ``add`` and
    ``mark`` extend the dirty rectangle by the item's bounds, ``remove``
    by where it was last painted, and ``flush`` paints the strips that
    rectangle touches, so a counter that marks one label repaints the
    one or two strips under it and nothing else.

    Args:
        panel: A panel driver: ``width``, ``height``, ``strip`` (the
            strip canvas it writes from), and
            ``write_strip(top, count, left, right)``, which sends
            columns ``left`` to ``right`` of ``count`` rows of the
            strip as one transfer to the panel rows from ``top``, or
            the full rows where the panel takes no column window.
        background: The pixel value the strip is cleared to before its
            items paint.
    """

    def __init__(self, panel: object, background: int = 0) -> None:
        self._panel = panel
        self._strip = panel.strip
        self.width = panel.width
        self.height = panel.height
        self.background = background
        self._items = []
        self._left = 0
        self._top = 0
        self._right = 0
        self._bottom = 0

    def add(self, item: object) -> None:
        """Append ``item`` above every item added before it and mark it."""
        self._items.append(item)
        self.mark(item)

    def remove(self, item: object) -> None:
        """Drop ``item`` from the scene and mark where it was painted."""
        self._items.remove(item)
        self._union(item.shown_left, item.shown_top, item.shown_right, item.shown_bottom)
        item.shown_right = item.shown_left

    def mark(self, item: object) -> None:
        """Record that ``item`` changed: it repaints where it was and where it is now."""
        item.layout(self._strip)
        self._union(item.shown_left, item.shown_top, item.shown_right, item.shown_bottom)
        self._union(item.left, item.top, item.right, item.bottom)
        item.shown_left = item.left
        item.shown_top = item.top
        item.shown_right = item.right
        item.shown_bottom = item.bottom

    def mark_all(self) -> None:
        """Repaint the whole panel on the next flush."""
        self._union(0, 0, self.width, self.height)

    def _union(self, left: int, top: int, right: int, bottom: int) -> None:
        """Extend the dirty rectangle by another, clipped to the panel."""
        if left < 0:
            left = 0
        if top < 0:
            top = 0
        if right > self.width:
            right = self.width
        if bottom > self.height:
            bottom = self.height
        if right <= left or bottom <= top:
            return
        if self._right <= self._left:
            self._left = left
            self._top = top
            self._right = right
            self._bottom = bottom
            return
        if left < self._left:
            self._left = left
        if top < self._top:
            self._top = top
        if right > self._right:
            self._right = right
        if bottom > self._bottom:
            self._bottom = bottom

    def flush(self) -> object:
        """Paint and send the strips the dirty rectangle touches, one per advance; the panel protocol.

        Each strip is windowed to the rectangle's columns: the strip
        lays itself out for them where its panel can send a column
        window, and the panel sends those columns of each row.
        """
        if self._right <= self._left:
            return
        left = self._left
        right = self._right
        top = self._top
        bottom = self._bottom
        self._left = 0
        self._right = 0
        strip = self._strip
        panel = self._panel
        rows = strip.rows
        height = self.height
        items = self._items
        background = self.background
        strip.window(left, right)
        row = top - top % rows
        while row < bottom:
            count = rows if row + rows <= height else height - row
            stop = row + count
            strip.top = row
            strip.clear(background)
            for item in items:
                if item.top < stop and item.bottom > row:
                    item.draw(strip)
            panel.write_strip(row, count, left, right)
            row = stop
            yield
