"""CPython-lane tests for ``Font`` over the CircuitPython canvas.

Seeds ``displayio``, ``bitmaptools``, and ``terminalio`` with the stubs
in ``_circuitpython_stubs`` and binds the font module's ``framebuf`` to
None, which is what a CircuitPython board looks like to it, so ``Font``
builds its glyph sheet and draws through ``BitmapCanvas.blit_bits``.
Every assert reads palette indexes back through ``BitmapCanvas.pixel``.
Silicon is covered by the functional bench.
"""

__chumicro_runtimes__ = ("cpython",)

import array
import sys

from _circuitpython_stubs import BitmaptoolsStub, DisplayioStub, TerminalioStub

sys.modules.setdefault("displayio", DisplayioStub())
sys.modules.setdefault("bitmaptools", BitmaptoolsStub())
sys.modules.setdefault("terminalio", TerminalioStub())

import pytest  # noqa: E402
from _font_stubs import FontModuleStub  # noqa: E402
from chumicro_screens import fonts  # noqa: E402
from chumicro_screens.bitmap_canvas import BitmapCanvas  # noqa: E402
from chumicro_screens.fonts import Font  # noqa: E402
from chumicro_screens.gc9a01a import color565  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402

WIDTH = 20
HEIGHT = 8


@pytest.fixture(autouse=True)
def _no_framebuf(monkeypatch):
    monkeypatch.setattr(fonts, "framebuf", None)


def make_canvas(frame_bits=16):
    """A canvas over a 16-bit frame holding colors, or an 8-bit one holding indexes."""
    if frame_bits == 8:
        bitmap = DisplayioStub.Bitmap(WIDTH, HEIGHT, 256)
        colors = bytes(range(256))
    else:
        bitmap = DisplayioStub.Bitmap(WIDTH, HEIGHT, 65536)
        colors = array.array("H", bytes(512))
        colors[1] = color565(255, 255, 255)
        colors[2] = color565(0, 255, 0)
        colors[3] = color565(0, 0, 255)
        colors[7] = color565(255, 0, 0)
    return BitmapCanvas(bitmap, colors, BitmaptoolsStub, TerminalioStub().FONT, DisplayioStub)


def row(canvas, y, x_start, count):  # noqa: CHU001 - framebuf's own names
    """The indexes across row ``y`` from column ``x_start``."""
    return [canvas.pixel(x, y) for x in range(x_start, x_start + count)]


def test_metrics_and_widths_match_the_framebuf_lane():
    font = Font(FontModuleStub())
    assert (font.height, font.baseline, font.max_width) == (4, 3, 9)
    assert font.width("AB") == 14
    assert font.width("Z") == 3


def test_text_draws_set_bits_in_the_index_and_leaves_clear_bits():
    canvas = make_canvas()
    canvas.fill(2)
    Font(FontModuleStub()).text(canvas, "A", 1, 1, 7)
    assert row(canvas, 0, 0, 7) == [2, 2, 2, 2, 2, 2, 2]
    assert row(canvas, 1, 0, 7) == [2, 2, 7, 7, 7, 2, 2]
    assert row(canvas, 2, 0, 7) == [2, 7, 2, 2, 2, 7, 2]
    assert row(canvas, 3, 0, 7) == [2, 7, 7, 7, 7, 7, 2]
    assert row(canvas, 5, 0, 7) == [2, 2, 2, 2, 2, 2, 2]


def test_glyphs_advance_by_their_own_widths_across_the_sheet():
    canvas = make_canvas()
    Font(FontModuleStub()).text(canvas, "AB", 0, 0, 1)
    assert row(canvas, 0, 0, 15) == [0, 1, 1, 1, 0] + [1] * 9 + [0]
    assert row(canvas, 1, 4, 11) == [1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0]


def test_white_and_black_text_both_dodge_the_scratch_sentinel():
    canvas = make_canvas()
    canvas.fill(2)
    font = Font(FontModuleStub())
    font.text(canvas, "C", 0, 0, 1)
    assert row(canvas, 0, 0, 4) == [1, 1, 1, 2]
    assert row(canvas, 1, 0, 4) == [1, 2, 2, 2]
    font.text(canvas, "C", 5, 0, 0)
    assert row(canvas, 0, 5, 4) == [0, 0, 0, 2]
    assert row(canvas, 1, 5, 4) == [0, 2, 2, 2]


def test_unknown_characters_draw_the_substitute_glyph():
    canvas = make_canvas()
    Font(FontModuleStub()).text(canvas, "Z", 0, 0, 3)
    assert row(canvas, 0, 0, 4) == [3, 3, 3, 0]
    assert row(canvas, 3, 0, 4) == [3, 3, 3, 0]


def test_text_clips_at_every_edge():
    canvas = make_canvas()
    font = Font(FontModuleStub())
    font.text(canvas, "B", -3, -1, 1)
    assert row(canvas, 0, 0, 7) == [0, 0, 0, 0, 0, 1, 0]
    assert row(canvas, 1, 0, 7) == [1, 1, 1, 1, 1, 1, 0]
    assert row(canvas, 2, 0, 7) == [0, 0, 0, 0, 0, 1, 0]
    font.text(canvas, "A", 17, 6, 1)
    assert row(canvas, 6, 17, 3) == [0, 1, 1]
    assert row(canvas, 7, 17, 3) == [1, 0, 0]
    before = bytes(canvas._bitmap)
    font.text(canvas, "A", 20, 0, 1)
    font.text(canvas, "A", 0, 8, 1)
    font.text(canvas, "A", -5, 0, 1)
    assert bytes(canvas._bitmap) == before


def test_a_vertically_mapped_module_is_refused():
    with raises(ValueError, match="horizontal"):
        Font(FontModuleStub(hmap=False))


def test_a_bit_reversed_module_draws_the_same_pixels():
    canvas = make_canvas()
    Font(FontModuleStub(reverse=True)).text(canvas, "A", 1, 1, 7)
    assert row(canvas, 1, 0, 7) == [0, 0, 7, 7, 7, 0, 0]
    assert row(canvas, 2, 0, 7) == [0, 7, 0, 0, 0, 7, 0]


def test_the_built_in_font_still_draws_through_the_shared_glyph_path():
    canvas = make_canvas()
    canvas.fill(2)
    canvas.text("A", 1, 1, 7)
    assert canvas.pixel(2, 2) == 7
    assert canvas.pixel(1, 1) == 2
    assert canvas.pixel(6, 2) == 2


def test_the_scratch_grows_to_the_largest_glyph_drawn():
    canvas = make_canvas()
    canvas.text("A", 0, 0, 7)
    assert (canvas._scratch.width, canvas._scratch.height) == (6, 12)
    Font(FontModuleStub()).text(canvas, "B", 0, 0, 7)
    assert (canvas._scratch.width, canvas._scratch.height) == (9, 12)
    assert canvas.pixel(8, 0) == 7


def test_an_8_bit_canvas_draws_indexes_including_zero_and_255():
    canvas = make_canvas(frame_bits=8)
    canvas.fill(3)
    font = Font(FontModuleStub())
    font.text(canvas, "C", 0, 0, 0)
    assert row(canvas, 0, 0, 4) == [0, 0, 0, 3]
    assert row(canvas, 1, 0, 4) == [0, 3, 3, 3]
    font.text(canvas, "C", 5, 0, 255)
    assert row(canvas, 0, 5, 4) == [255, 255, 255, 3]
    assert row(canvas, 1, 5, 4) == [255, 3, 3, 3]
