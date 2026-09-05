"""Host-lane tests for ``chumicro_screens.fonts.Font`` over the framebuf canvas.

Runs on CPython and both unix ports.  Where the runtime ships
``framebuf`` (the MicroPython port) the real C blit draws, which is
the path a board takes; elsewhere the shared stub stands in.  The
asserts read the values a glyph leaves in an 8-bit frame, a 1-bit
``MONO_VLSB`` frame like the OLED's, and a 16-bit ``RGB565`` frame.
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
from chumicro_screens.framebuf_canvas import FramebufCanvas  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402

WIDTH = 20
HEIGHT = 8


def make_canvas(pixel_format: int | None = None) -> tuple:
    """A canvas over a fresh buffer: 8-bit by default, or the mono or 16-bit format asked for."""
    if pixel_format is None:
        pixel_format = framebuf.GS8
    size = {framebuf.GS8: WIDTH * HEIGHT, framebuf.MONO_VLSB: WIDTH * (HEIGHT // 8),
            framebuf.RGB565: WIDTH * HEIGHT * 2}[pixel_format]
    buffer = bytearray(size)
    return FramebufCanvas(buffer, WIDTH, HEIGHT, pixel_format), buffer


def row(buffer: bytearray, y: int, x_start: int, count: int) -> list:  # noqa: CHU001 - framebuf's own names
    """The indexes across row ``y`` from column ``x_start``."""
    start = y * WIDTH + x_start
    return list(buffer[start:start + count])


def test_metrics_come_from_the_module() -> None:
    """height, baseline, and max_width are the module's numbers."""
    font = Font(FontModuleStub())
    assert font.height == 4
    assert font.baseline == 3
    assert font.max_width == 9


def test_width_sums_glyph_widths_and_substitutes_unknown_characters() -> None:
    """A string's width is its glyph widths summed, with the module's fallback for unknown ones."""
    font = Font(FontModuleStub())
    assert font.width("AB") == 14
    assert font.width("") == 0
    assert font.width("Z") == font.width("C") == 3


def test_text_draws_set_bits_in_the_index_and_leaves_clear_bits() -> None:
    """Set bits land as the index at (x, y); clear bits and the rows around keep the fill."""
    canvas, buffer = make_canvas()
    canvas.fill(2)
    Font(FontModuleStub()).text(canvas, "A", 1, 1, 7)
    assert row(buffer, 0, 0, 7) == [2, 2, 2, 2, 2, 2, 2]
    assert row(buffer, 1, 0, 7) == [2, 2, 7, 7, 7, 2, 2]
    assert row(buffer, 2, 0, 7) == [2, 7, 2, 2, 2, 7, 2]
    assert row(buffer, 3, 0, 7) == [2, 7, 7, 7, 7, 7, 2]
    assert row(buffer, 4, 0, 7) == [2, 7, 2, 2, 2, 7, 2]
    assert row(buffer, 5, 0, 7) == [2, 2, 2, 2, 2, 2, 2]


def test_glyphs_advance_by_their_own_widths() -> None:
    """After a 5-wide A, the 9-wide B starts at column 5 and ends at column 13."""
    canvas, buffer = make_canvas()
    Font(FontModuleStub()).text(canvas, "AB", 0, 0, 1)
    assert row(buffer, 0, 0, 15) == [0, 1, 1, 1, 0] + [1] * 9 + [0]
    assert row(buffer, 1, 4, 11) == [1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0]


def test_index_zero_draws_over_a_colored_background() -> None:
    """Index 0 text lands as 0 on a fill of 3 and the clear bits stay 3."""
    canvas, buffer = make_canvas()
    canvas.fill(3)
    Font(FontModuleStub()).text(canvas, "C", 0, 0, 0)
    assert row(buffer, 0, 0, 4) == [0, 0, 0, 3]
    assert row(buffer, 1, 0, 4) == [0, 3, 3, 3]
    assert row(buffer, 3, 0, 4) == [0, 0, 0, 3]


def test_text_clips_at_every_edge() -> None:
    """Glyphs past the top-left and bottom-right edges draw their visible pixels only."""
    canvas, buffer = make_canvas()
    font = Font(FontModuleStub())
    font.text(canvas, "B", -3, -1, 1)
    assert row(buffer, 0, 0, 7) == [0, 0, 0, 0, 0, 1, 0]
    assert row(buffer, 1, 0, 7) == [1, 1, 1, 1, 1, 1, 0]
    assert row(buffer, 2, 0, 7) == [0, 0, 0, 0, 0, 1, 0]
    font.text(canvas, "A", 17, 6, 1)
    assert row(buffer, 6, 17, 3) == [0, 1, 1]
    assert row(buffer, 7, 17, 3) == [1, 0, 0]
    before = bytes(buffer)
    font.text(canvas, "A", 20, 0, 1)
    font.text(canvas, "A", 0, 8, 1)
    font.text(canvas, "A", -5, 0, 1)
    assert bytes(buffer) == before


def test_a_vertically_mapped_module_is_refused() -> None:
    """A module reporting hmap() False raises ValueError naming the -x conversion."""
    with raises(ValueError, match="horizontal"):
        Font(FontModuleStub(hmap=False))


def test_text_on_a_mono_frame_sets_bits_and_leaves_the_rest() -> None:
    """On a MONO_VLSB frame a glyph's set bits land as 1 on a dark fill and as 0 on a lit one."""
    canvas, _ = make_canvas(framebuf.MONO_VLSB)
    font = Font(FontModuleStub())
    font.text(canvas, "A", 1, 1, 1)
    assert [canvas.pixel(x, 1) for x in range(7)] == [0, 0, 1, 1, 1, 0, 0]
    assert [canvas.pixel(x, 2) for x in range(7)] == [0, 1, 0, 0, 0, 1, 0]
    assert [canvas.pixel(x, 0) for x in range(7)] == [0] * 7
    canvas.fill(1)
    font.text(canvas, "C", 0, 0, 0)
    assert [canvas.pixel(x, 0) for x in range(4)] == [0, 0, 0, 1]
    assert [canvas.pixel(x, 1) for x in range(4)] == [0, 1, 1, 1]


def test_text_on_a_16_bit_frame_draws_the_color_value() -> None:
    """On an RGB565 frame the set bits carry the value given, black and white included."""
    canvas, _ = make_canvas(framebuf.RGB565)
    font = Font(FontModuleStub())
    font.text(canvas, "A", 1, 1, 0xABCD)
    assert canvas.pixel(2, 1) == 0xABCD
    assert canvas.pixel(1, 1) == 0
    assert canvas.pixel(1, 2) == 0xABCD
    font.text(canvas, "C", 10, 0, 0xFFFF)
    assert canvas.pixel(10, 0) == 0xFFFF
    assert canvas.pixel(11, 1) == 0
    canvas.fill(0x1234)
    font.text(canvas, "C", 0, 0, 0)
    assert canvas.pixel(0, 0) == 0
    assert canvas.pixel(1, 1) == 0x1234


def test_one_font_follows_each_canvas_it_draws_on() -> None:
    """The palette is rebuilt for a canvas of another format and the earlier one still draws right."""
    font = Font(FontModuleStub())
    indexed, _ = make_canvas()
    mono, _ = make_canvas(framebuf.MONO_VLSB)
    font.text(indexed, "A", 0, 0, 9)
    font.text(mono, "A", 0, 0, 1)
    font.text(indexed, "A", 10, 0, 7)
    assert indexed.pixel(1, 0) == 9
    assert mono.pixel(1, 0) == 1
    assert indexed.pixel(11, 0) == 7
    assert indexed.pixel(10, 0) == 0


def test_a_bit_reversed_module_draws_the_same_pixels() -> None:
    """A module converted with -r renders A at the same pixels as the plain one."""
    canvas, buffer = make_canvas()
    Font(FontModuleStub(reverse=True)).text(canvas, "A", 1, 1, 7)
    assert row(buffer, 1, 0, 7) == [0, 0, 7, 7, 7, 0, 0]
    assert row(buffer, 2, 0, 7) == [0, 7, 0, 0, 0, 7, 0]
