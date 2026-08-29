"""Shared ``framebuf`` stub for the cross-runtime screens driver tests.

The MicroPython panel drivers build their frame on
``framebuf.FrameBuffer``.  CPython has no ``framebuf`` at all, and
CircuitPython's display layer is ``displayio``, so neither host runtime
supplies one.  Each driver test file seeds ``sys.modules`` with this
stub before importing its driver so the construction-time import
succeeds and the tests can assert on the bytes the driver puts on the
bus.

The stub is shared rather than copied per test file because
``sys.modules.setdefault`` leaves the winner decided by collection
order: a stub carrying only the formats one driver needs would fail the
other's import when it happened to load first.

Plain classes rather than ``types.ModuleType`` instances because the MP
and CP unix-ports omit the ``types`` module.

This module is staged onto the device next to the importing test file by
the pytest-device staging path (underscore-prefixed sibling modules ride
along as ``extra_modules``); on the host and unix-port runs the test
file's directory is on ``sys.path`` so ``from _framebuf_stub import ...``
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
      so byte ``(y // 8) * width + x`` carries row ``y`` in bit
      ``y % 8``.

    ``blit`` implements the one conversion the color drivers use, a GS8
    source through a 256-entry palette into an RGB565 destination, with
    real clipping, so tests assert on real bytes rather than on stub
    bookkeeping.
    """

    MONO_VLSB = 0
    RGB565 = 1
    GS8 = 2

    class FrameBuffer:
        def __init__(self, buffer, width, height, pixel_format):
            self.buffer = buffer
            self.width = width
            self.height = height
            self.pixel_format = pixel_format

        # framebuf's own signature names the coordinates x and y.
        def pixel(self, x, y, value):  # noqa: CHU001
            if self.pixel_format == FramebufStub.MONO_VLSB:
                offset = (y // 8) * self.width + x
                mask = 1 << (y % 8)
                if value:
                    self.buffer[offset] |= mask
                else:
                    self.buffer[offset] &= ~mask & 0xFF
                return
            if self.pixel_format == FramebufStub.GS8:
                self.buffer[y * self.width + x] = value & 0xFF
                return
            offset = (y * self.width + x) * 2
            self.buffer[offset] = value & 0xFF
            self.buffer[offset + 1] = value >> 8

        # framebuf's own signature names the coordinates x and y.
        def blit(self, source, x, y, key=-1, palette=None):  # noqa: CHU001
            for source_y in range(source.height):
                dest_y = y + source_y
                if not 0 <= dest_y < self.height:
                    continue
                for source_x in range(source.width):
                    dest_x = x + source_x
                    if not 0 <= dest_x < self.width:
                        continue
                    value = source.buffer[source_y * source.width + source_x]
                    if value == key:
                        continue
                    if palette is not None:
                        entry = value * 2
                        value = (palette.buffer[entry]
                                 | (palette.buffer[entry + 1] << 8))
                    offset = (dest_y * self.width + dest_x) * 2
                    self.buffer[offset] = value & 0xFF
                    self.buffer[offset + 1] = value >> 8
