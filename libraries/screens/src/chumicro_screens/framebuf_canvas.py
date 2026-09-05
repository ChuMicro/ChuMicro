"""``framebuf.FrameBuffer`` as the portable canvas: the same drawing, plus the bounds of what it drew.

``FramebufCanvas`` is what ``GC9A01AIndexed.frame`` is on MicroPython.
It is a ``framebuf.FrameBuffer``, so every primitive still runs in C
and any framebuf source blits into it, and each primitive first
records the rectangle it is about to touch.  ``take_dirty`` hands that
rectangle to the panel, whose flush sends the strips covering it
rather than the whole frame.  Code that writes the buffer behind the
canvas's back, a decoder filling rows by ``readinto`` for instance,
marks its region with ``dirty``.
"""

__chumicro_runtimes__ = ("micropython",)

import framebuf

_GLYPH_SIZE = 8


class FramebufCanvas(framebuf.FrameBuffer):
    """A ``framebuf.FrameBuffer`` that records the bounds of everything drawn on it.

    The methods are framebuf's own, with the same arguments and the
    same clipping, and ``width`` and ``height`` are readable, which
    framebuf leaves out.  Each call costs one Python frame and its
    bookkeeping on top of the C primitive, about 110 us on an RP2040
    against 28 us for a bare ``pixel``, so per-pixel loops should batch
    through ``blit`` as they should on the CircuitPython canvas.  A new
    canvas starts wholly dirty, since the panel has not yet seen its
    buffer.

    Args:
        buffer: The frame's bytes, ``width * height`` of them for
            ``framebuf.GS8``.
        width: Frame width in pixels.
        height: Frame height in pixels.
        pixel_format: A ``framebuf`` format constant.
        stride: Pixels between the starts of consecutive rows; the
            width when omitted.
    """

    def __init__(self, buffer: object, width: int, height: int,  # noqa: CHU001 - framebuf's own names
                 pixel_format: int, stride: int | None = None) -> None:
        if stride is None:
            super().__init__(buffer, width, height, pixel_format)
        else:
            super().__init__(buffer, width, height, pixel_format, stride)
        self.width = width
        self.height = height
        self._left = 0
        self._top = 0
        self._right = width
        self._bottom = height

    def dirty(self, x: int, y: int, width: int, height: int) -> None:  # noqa: CHU001 - framebuf's own names
        """Mark a rectangle as changed, for pixels written behind the canvas's back.

        Args:
            x: Left column of the rectangle.
            y: Top row of the rectangle.
            width: Rectangle width in pixels.
            height: Rectangle height in pixels.
        """
        self._mark(x, y, x + width, y + height)

    def take_dirty(self) -> tuple:
        """Return the bounds of everything drawn since the last call, and start afresh.

        The bounds are ``(left, top, right, bottom)`` with ``right``
        and ``bottom`` exclusive, clipped to the frame; ``(0, 0, 0, 0)``
        when nothing was drawn.
        """
        left = self._left
        right = self._right
        if left >= right:
            return (0, 0, 0, 0)
        result = (left, self._top, right, self._bottom)
        self._left = self.width
        self._top = self.height
        self._right = 0
        self._bottom = 0
        return result

    def _mark(self, left: int, top: int, right: int, bottom: int) -> None:
        """Union a rectangle into the dirty bounds, clipped to the frame."""
        if left < 0:
            left = 0
        if top < 0:
            top = 0
        if right > self.width:
            right = self.width
        if bottom > self.height:
            bottom = self.height
        if left >= right or top >= bottom:
            return
        if left < self._left:
            self._left = left
        if top < self._top:
            self._top = top
        if right > self._right:
            self._right = right
        if bottom > self._bottom:
            self._bottom = bottom

    def fill(self, index: int) -> None:
        self._mark(0, 0, self.width, self.height)
        super().fill(index)

    def fill_rect(self, x: int, y: int, width: int, height: int,  # noqa: CHU001 - framebuf's own names
                  index: int) -> None:
        self._mark(x, y, x + width, y + height)
        super().fill_rect(x, y, width, height, index)

    def rect(self, x: int, y: int, width: int, height: int, index: int,  # noqa: CHU001 - framebuf's own names
             fill: bool = False) -> None:
        self._mark(x, y, x + width, y + height)
        super().rect(x, y, width, height, index, fill)

    def hline(self, x: int, y: int, width: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        self._mark(x, y, x + width, y + 1)
        super().hline(x, y, width, index)

    def vline(self, x: int, y: int, height: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        self._mark(x, y, x + 1, y + height)
        super().vline(x, y, height, index)

    def pixel(self, x: int, y: int, index: int | None = None) -> int | None:  # noqa: CHU001 - framebuf's own names
        """Set one pixel, or with ``index`` omitted return the index drawn there."""
        if index is None:
            return super().pixel(x, y)
        if 0 <= x < self.width and 0 <= y < self.height:
            if x < self._left:
                self._left = x
            if y < self._top:
                self._top = y
            if x >= self._right:
                self._right = x + 1
            if y >= self._bottom:
                self._bottom = y + 1
            super().pixel(x, y, index)
        return None

    def line(self, x1: int, y1: int, x2: int, y2: int, index: int) -> None:  # noqa: CHU001 - framebuf's own names
        self._mark(min(x1, x2), min(y1, y2), max(x1, x2) + 1, max(y1, y2) + 1)
        super().line(x1, y1, x2, y2, index)

    def ellipse(self, x: int, y: int, x_radius: int, y_radius: int,  # noqa: CHU001 - framebuf's own names
                index: int, fill: bool = False, mask: int = 0xF) -> None:
        """Draw an ellipse; ``mask`` selects quadrants, a framebuf extra the CircuitPython canvas lacks."""
        self._mark(x - x_radius, y - y_radius, x + x_radius + 1, y + y_radius + 1)
        super().ellipse(x, y, x_radius, y_radius, index, fill, mask)

    def poly(self, x: int, y: int, coords: object, index: int,  # noqa: CHU001 - framebuf's own names
             fill: bool = False) -> None:
        """Draw a closed polygon through ``coords``, an array of x, y pairs offset by (x, y)."""
        count = len(coords) // 2
        if count:
            left = right = coords[0]
            top = bottom = coords[1]
            for point in range(1, count):
                point_x = coords[2 * point]
                point_y = coords[2 * point + 1]
                if point_x < left:
                    left = point_x
                elif point_x > right:
                    right = point_x
                if point_y < top:
                    top = point_y
                elif point_y > bottom:
                    bottom = point_y
            self._mark(x + left, y + top, x + right + 1, y + bottom + 1)
        super().poly(x, y, coords, index, fill)

    def blit(self, source: object, x: int, y: int, key: int = -1,  # noqa: CHU001 - framebuf's own names
             palette: object | None = None) -> None:
        """Copy a framebuf source in, skipping pixels whose mapped value is ``key``.

        The source is another ``FramebufCanvas``, a ``(buffer, width,
        height, format)`` list or tuple, or a bare ``FrameBuffer``.  A
        bare one reports no size, so its blit dirties everything right
        of and below (x, y).
        """
        if isinstance(source, FramebufCanvas):
            width = source.width
            height = source.height
        elif isinstance(source, (list, tuple)):
            width = source[1]
            height = source[2]
        else:
            width = self.width
            height = self.height
        self._mark(x, y, x + width, y + height)
        super().blit(source, x, y, key, palette)

    def text(self, string: str, x: int, y: int, index: int = 1) -> None:  # noqa: CHU001 - framebuf's own names
        """Draw ``string`` in framebuf's 8x8 font with its top-left at (x, y)."""
        self._mark(x, y, x + _GLYPH_SIZE * len(string), y + _GLYPH_SIZE)
        super().text(string, x, y, index)

    def scroll(self, x_step: int, y_step: int) -> None:
        """Shift the whole frame, a framebuf extra the CircuitPython canvas lacks."""
        self._mark(0, 0, self.width, self.height)
        super().scroll(x_step, y_step)
