"""Host-lane tests for ``chumicro_screens.fonts.Font`` over a framebuf canvas.

Runs on CPython and both unix ports.  Where the runtime ships
``framebuf`` (the MicroPython port) the real C blit draws, which is
the path a board takes; elsewhere the shared stub stands in.  Every
assert reads the palette indexes a glyph leaves in an 8-bit frame.
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


def make_canvas() -> tuple:
    buffer = bytearray(WIDTH * HEIGHT)
    return framebuf.FrameBuffer(buffer, WIDTH, HEIGHT, framebuf.GS8), buffer


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


def test_a_bit_reversed_module_draws_the_same_pixels() -> None:
    """A module converted with -r renders A at the same pixels as the plain one."""
    canvas, buffer = make_canvas()
    Font(FontModuleStub(reverse=True)).text(canvas, "A", 1, 1, 7)
    assert row(buffer, 1, 0, 7) == [0, 0, 7, 7, 7, 0, 0]
    assert row(buffer, 2, 0, 7) == [0, 7, 0, 0, 0, 7, 0]
