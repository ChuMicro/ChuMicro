"""Shared ``sys.modules`` stubs for the cross-runtime screens tests.

The MicroPython panel drivers build their frame on
``framebuf.FrameBuffer``; the CircuitPython factories hand their panel
to ``busdisplay.BusDisplay``.  Neither module exists on a host runtime:
CPython has no ``framebuf`` and no displayio, and CircuitPython's
display layer is displayio rather than framebuf.  Each driver test file
seeds ``sys.modules`` with the stub it needs before importing its
driver, so the module-load import succeeds and the tests can assert on
what the driver hands the firmware.

The stubs are shared rather than copied per test file because
``sys.modules.setdefault`` leaves the winner decided by collection
order: a stub carrying only what one driver needs would fail the
other's import when it happened to load first.

Plain classes rather than ``types.ModuleType`` instances because the MP
and CP unix-ports omit the ``types`` module.

This module is staged onto the device next to the importing test file by
the pytest-device staging path (underscore-prefixed sibling modules ride
along as ``extra_modules``); on the host and unix-port runs the test
file's directory is on ``sys.path`` so ``from _screen_stubs import ...``
resolves there too.
"""

#: Host-only support module: stubs a firmware module so off-target
#: driver source loads on host interpreters.  Carries no runtime marker
#: because it ships alongside the test files that import it and never
#: runs standalone.
__chumicro_test_support__ = True


class FramebufStub:
    """Stand-in for ``framebuf`` on host runtimes that lack it.

    ``FrameBuffer`` dispatches on the pixel format it was built with:

    - ``RGB565`` stores two little-endian bytes per pixel.
    - ``GS8`` stores one byte per pixel.
    - ``MONO_VLSB`` packs eight vertically stacked pixels into one byte,
      so byte ``(y // 8) * stride + x`` carries row ``y`` in bit
      ``y % 8``; ``stride`` defaults to the width, as in framebuf.
    - ``MONO_HLSB`` and ``MONO_HMSB`` pack eight horizontal pixels into
      one byte, most significant bit first for HLSB and least first for
      HMSB, with every row padded to whole bytes as framebuf pads it.

    ``blit`` follows framebuf: the source is a ``FrameBuffer`` or a
    ``(buffer, width, height, format[, stride])`` sequence, each source
    pixel maps through the palette when one is given (a one-row
    ``FrameBuffer`` in the destination's format), and a mapped value
    equal to ``key`` is skipped.  Clipping is real, so tests assert on
    real bytes rather than on stub bookkeeping.  The shape primitives
    clip as framebuf's do: ``fill_rect`` trims to the frame and draws
    nothing for a non-positive size, ``ellipse`` walks framebuf's own
    midpoint loop with its quadrant mask, ``poly`` closes the outline
    and fills by even-odd scanline, and out-of-range pixels are
    dropped.  ``text`` has no font: every character fills its whole
    8x8 cell, so a test can see where the cells land but not a glyph.
    """

    MONO_VLSB = 0
    RGB565 = 1
    GS8 = 2
    MONO_HLSB = 3
    MONO_HMSB = 4

    class FrameBuffer:
        def __init__(self, buffer, width, height, pixel_format, stride=None):
            self.buffer = buffer
            self.width = width
            self.height = height
            self.pixel_format = pixel_format
            if stride is None:
                stride = width
            if pixel_format in (FramebufStub.MONO_HLSB, FramebufStub.MONO_HMSB):
                stride = (stride + 7) & ~7
            self.stride = stride

        # framebuf's own signature names the coordinates x and y.
        def pixel(self, x, y, value=None):  # noqa: CHU001
            """Set pixel (x, y) to ``value``, or with ``value`` omitted return it.

            Outside the frame a write is dropped and a read returns
            None, as framebuf does.
            """
            if not (0 <= x < self.width and 0 <= y < self.height):
                return None
            pixel_format = self.pixel_format
            if pixel_format == FramebufStub.GS8:
                offset = y * self.width + x
                if value is None:
                    return self.buffer[offset]
                self.buffer[offset] = value & 0xFF
                return None
            if pixel_format == FramebufStub.RGB565:
                offset = (y * self.width + x) * 2
                if value is None:
                    return self.buffer[offset] | (self.buffer[offset + 1] << 8)
                self.buffer[offset] = value & 0xFF
                self.buffer[offset + 1] = value >> 8
                return None
            if pixel_format == FramebufStub.MONO_VLSB:
                offset = (y // 8) * self.stride + x
                mask = 1 << (y % 8)
            else:
                offset = y * (self.stride >> 3) + (x >> 3)
                if pixel_format == FramebufStub.MONO_HLSB:
                    mask = 0x80 >> (x & 7)
                else:
                    mask = 1 << (x & 7)
            if value is None:
                return 1 if self.buffer[offset] & mask else 0
            if value:
                self.buffer[offset] |= mask
            else:
                self.buffer[offset] &= ~mask & 0xFF
            return None

        def fill(self, value):
            for y in range(self.height):
                for x in range(self.width):
                    self.pixel(x, y, value)

        # framebuf's own signature names the coordinates x and y.
        def fill_rect(self, x, y, width, height, value):  # noqa: CHU001
            if width < 1 or height < 1:
                return
            for row in range(max(y, 0), min(self.height, y + height)):
                for column in range(max(x, 0), min(self.width, x + width)):
                    self.pixel(column, row, value)

        def hline(self, x, y, width, value):  # noqa: CHU001
            self.fill_rect(x, y, width, 1, value)

        def vline(self, x, y, height, value):  # noqa: CHU001
            self.fill_rect(x, y, 1, height, value)

        def rect(self, x, y, width, height, value, fill=False):  # noqa: CHU001
            if fill:
                self.fill_rect(x, y, width, height, value)
                return
            self.fill_rect(x, y, width, 1, value)
            self.fill_rect(x, y + height - 1, width, 1, value)
            self.fill_rect(x, y, 1, height, value)
            self.fill_rect(x + width - 1, y, 1, height, value)

        def line(self, x1, y1, x2, y2, value):  # noqa: CHU001
            delta_x = abs(x2 - x1)
            delta_y = -abs(y2 - y1)
            step_x = 1 if x1 < x2 else -1
            step_y = 1 if y1 < y2 else -1
            error = delta_x + delta_y
            while True:
                self.pixel(x1, y1, value)
                if x1 == x2 and y1 == y2:
                    return
                doubled = 2 * error
                if doubled >= delta_y:
                    error += delta_y
                    x1 += step_x
                if doubled <= delta_x:
                    error += delta_x
                    y1 += step_y

        def _ellipse_points(self, center_x, center_y, x, y, value, fill, mask):  # noqa: CHU001
            """framebuf's ``draw_ellipse_points``: one point or span per enabled quadrant."""
            if fill:
                spans = ((center_x, center_y - y), (center_x - x, center_y - y),
                         (center_x - x, center_y + y), (center_x, center_y + y))
                for quadrant in range(4):
                    if mask & (1 << quadrant):
                        self.fill_rect(spans[quadrant][0], spans[quadrant][1], x + 1, 1, value)
                return
            points = ((center_x + x, center_y - y), (center_x - x, center_y - y),
                      (center_x - x, center_y + y), (center_x + x, center_y + y))
            for quadrant in range(4):
                if mask & (1 << quadrant):
                    self.pixel(points[quadrant][0], points[quadrant][1], value)

        def ellipse(self, x, y, x_radius, y_radius, value, fill=False, mask=0xF):  # noqa: CHU001
            """framebuf's midpoint ellipse, both arcs, with its quadrant mask."""
            two_a_square = 2 * x_radius * x_radius
            two_b_square = 2 * y_radius * y_radius
            point_x = x_radius
            point_y = 0
            x_change = y_radius * y_radius * (1 - 2 * x_radius)
            y_change = x_radius * x_radius
            error = 0
            stopping_x = two_b_square * x_radius
            stopping_y = 0
            while stopping_x >= stopping_y:
                self._ellipse_points(x, y, point_x, point_y, value, fill, mask)
                point_y += 1
                stopping_y += two_a_square
                error += y_change
                y_change += two_a_square
                if 2 * error + x_change > 0:
                    point_x -= 1
                    stopping_x -= two_b_square
                    error += x_change
                    x_change += two_b_square
            point_x = 0
            point_y = y_radius
            x_change = y_radius * y_radius
            y_change = x_radius * x_radius * (1 - 2 * y_radius)
            error = 0
            stopping_x = 0
            stopping_y = two_a_square * y_radius
            while stopping_x <= stopping_y:
                self._ellipse_points(x, y, point_x, point_y, value, fill, mask)
                point_x += 1
                stopping_x += two_b_square
                error += x_change
                x_change += two_b_square
                if 2 * error + y_change > 0:
                    point_y -= 1
                    stopping_y -= two_a_square
                    error += y_change
                    y_change += two_a_square

        def poly(self, x, y, coords, value, fill=False):  # noqa: CHU001
            count = len(coords) // 2
            points = [(x + coords[2 * point], y + coords[2 * point + 1])
                      for point in range(count)]
            if not fill:
                for point in range(count):
                    start = points[point]
                    end = points[(point + 1) % count]
                    self.line(start[0], start[1], end[0], end[1], value)
                return
            for row in range(min(point[1] for point in points),
                             max(point[1] for point in points) + 1):
                crossings = []
                for point in range(count):
                    (start_x, start_y), (end_x, end_y) = points[point], points[(point + 1) % count]
                    if (start_y <= row) != (end_y <= row):
                        crossings.append(start_x + (row - start_y) * (end_x - start_x)
                                         // (end_y - start_y))
                crossings.sort()
                for pair in range(0, len(crossings) - 1, 2):
                    self.hline(crossings[pair], row, crossings[pair + 1] - crossings[pair] + 1,
                               value)

        def text(self, string, x, y, value=1):  # noqa: CHU001
            for cell in range(len(string)):
                self.fill_rect(x + 8 * cell, y, 8, 8, value)

        def scroll(self, x_step, y_step):
            rows = [[self.pixel(x, y) for x in range(self.width)] for y in range(self.height)]
            for y in range(self.height):
                for x in range(self.width):
                    source_x = x - x_step
                    source_y = y - y_step
                    if 0 <= source_x < self.width and 0 <= source_y < self.height:
                        self.pixel(x, y, rows[source_y][source_x])

        # framebuf's own signature names the coordinates x and y.
        def blit(self, source, x, y, key=-1, palette=None):  # noqa: CHU001
            if not isinstance(source, FramebufStub.FrameBuffer):
                source = FramebufStub.FrameBuffer(*source)
            for source_y in range(source.height):
                dest_y = y + source_y
                if not 0 <= dest_y < self.height:
                    continue
                for source_x in range(source.width):
                    dest_x = x + source_x
                    if not 0 <= dest_x < self.width:
                        continue
                    value = source.pixel(source_x, source_y)
                    if palette is not None:
                        value = palette.pixel(value, 0)
                    if value != key:
                        self.pixel(dest_x, dest_y, value)


class BusDisplayStub:
    """Stand-in for ``busdisplay`` on runtimes without displayio.

    ``BusDisplay`` takes its panel arguments by keyword and records
    them, exposing each as an attribute too, so a test can read either
    ``display.kwargs["color_depth"]`` or ``display.width``.  The real
    constructor's keyword set differs per panel family, which is why
    this one captures rather than names them.
    """

    class BusDisplay:
        def __init__(self, display_bus, init_sequence, **kwargs):
            self.display_bus = display_bus
            self.init_sequence = bytes(init_sequence)
            self.kwargs = kwargs
            for name, value in kwargs.items():
                setattr(self, name, value)
