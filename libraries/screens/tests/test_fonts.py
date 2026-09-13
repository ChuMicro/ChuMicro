"""Host-lane tests for ``chumicro_screens.fonts.Font`` drawing into a framebuf.

Runs on CPython and both unix ports.  Where the runtime ships
``framebuf`` (the MicroPython port) the real C blit draws, which is
the path a board takes; elsewhere the shared stub stands in.  The
asserts read the values a glyph leaves in an 8-bit buffer, a 1-bit
``MONO_VLSB`` buffer like the OLED's page, and a 16-bit ``RGB565``
buffer like the round TFT's strip.
"""

__chumicro_host_only__ = True

import sys

from _screen_stubs import FramebufStub

try:
    import framebuf
except ImportError:
    framebuf = FramebufStub()
    sys.modules["framebuf"] = framebuf

from _font_stubs import FontModuleStub  # noqa: E402
from chumicro_screens.fonts import Font  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402

WIDTH = 20
HEIGHT = 8


def make_buffer(pixel_format: int | None = None) -> tuple:
    """A framebuf over a fresh buffer: 8-bit by default, or the mono or 16-bit format asked for."""
    if pixel_format is None:
        pixel_format = framebuf.GS8
    size = {framebuf.GS8: WIDTH * HEIGHT, framebuf.MONO_VLSB: WIDTH * (HEIGHT // 8),
            framebuf.RGB565: WIDTH * HEIGHT * 2}[pixel_format]
    buffer = bytearray(size)
    return framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, pixel_format), buffer, pixel_format


def row(buffer: bytearray, y: int, x_start: int, count: int) -> list:  # noqa: CHU001 - framebuf's own names
    """The values across row ``y`` of an 8-bit buffer from column ``x_start``."""
    start = y * WIDTH + x_start
    return list(buffer[start:start + count])


def test_metrics_come_from_the_module() -> None:
    font = Font(FontModuleStub())
    assert font.height == 4
    assert font.baseline == 3
    assert font.max_width == 9


def test_width_sums_glyph_widths_and_substitutes_unknown_characters() -> None:
    font = Font(FontModuleStub())
    assert font.width("AB") == 14
    assert font.width("") == 0
    assert font.width("Z") == font.width("C") == 3


def test_a_vertically_mapped_module_is_refused() -> None:
    with raises(ValueError):
        Font(FontModuleStub(hmap=False))


def test_draw_sets_the_glyph_bits_in_the_value_and_leaves_the_rest() -> None:
    """Set bits land as the value at (x, y); clear bits and the rows around keep the fill."""
    target, buffer, pixel_format = make_buffer()
    target.fill(2)
    Font(FontModuleStub()).draw(target, pixel_format, "A", 1, 1, 7)
    assert row(buffer, 0, 0, 7) == [2, 2, 2, 2, 2, 2, 2]
    assert row(buffer, 1, 0, 7) == [2, 2, 7, 7, 7, 2, 2]
    assert row(buffer, 2, 0, 7) == [2, 7, 2, 2, 2, 7, 2]
    assert row(buffer, 3, 0, 7) == [2, 7, 7, 7, 7, 7, 2]
    assert row(buffer, 5, 0, 7) == [2, 2, 2, 2, 2, 2, 2]


def test_draw_advances_by_each_glyph_width_and_clips_at_the_edge() -> None:
    target, buffer, pixel_format = make_buffer()
    Font(FontModuleStub()).draw(target, pixel_format, "CA", 14, 0, 1)
    assert row(buffer, 0, 14, 6) == [1, 1, 1, 0, 1, 1]
    assert row(buffer, 1, 14, 6) == [1, 0, 0, 1, 0, 0]


def test_draw_works_in_the_mono_and_16_bit_formats_and_a_reversed_module() -> None:
    mono, _, mono_format = make_buffer(framebuf.MONO_VLSB)
    Font(FontModuleStub()).draw(mono, mono_format, "A", 0, 0, 1)
    assert [mono.pixel(x, 0) for x in range(5)] == [0, 1, 1, 1, 0]
    assert [mono.pixel(x, 1) for x in range(5)] == [1, 0, 0, 0, 1]

    color, _, color_format = make_buffer(framebuf.RGB565)
    color.fill(0x1234)
    Font(FontModuleStub(reverse=True)).draw(color, color_format, "A", 0, 0, 0xABCD)
    assert [color.pixel(x, 0) for x in range(5)] == [0x1234, 0xABCD, 0xABCD, 0xABCD, 0x1234]


def test_draw_in_value_zero_leaves_clear_bits_alone() -> None:
    target, buffer, pixel_format = make_buffer()
    target.fill(9)
    Font(FontModuleStub()).draw(target, pixel_format, "A", 0, 0, 0)
    assert row(buffer, 0, 0, 5) == [9, 0, 0, 0, 9]
