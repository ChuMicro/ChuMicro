"""CPython-lane tests for ``BitmapStrip``, the CircuitPython strip canvas.

Seeds ``displayio``, ``bitmaptools``, and ``terminalio`` with the stubs
in ``_circuitpython_stubs``, whose ``fill_region`` and ``blit`` refuse
out-of-range coordinates the way the firmware's do, so the asserts
cover the clipping the strip performs before each call as well as the
pixels each primitive leaves in a strip whose ``top`` is not zero.
Silicon is covered by the functional bench.
"""

__chumicro_runtimes__ = ("cpython",)

import sys

from _circuitpython_stubs import BitmaptoolsStub, DisplayioStub, TerminalioStub
from _screen_stubs import FramebufStub

sys.modules.setdefault("displayio", DisplayioStub())
sys.modules.setdefault("bitmaptools", BitmaptoolsStub())
sys.modules.setdefault("terminalio", TerminalioStub())
# The font module binds framebuf once at import; the framebuf-lane
# files in this session expect the stub there, whichever file loads
# the module first.
sys.modules.setdefault("framebuf", FramebufStub())

from _font_stubs import FontModuleStub  # noqa: E402
from chumicro_screens import fonts  # noqa: E402
from chumicro_screens.bitmap_strip import BitmapStrip  # noqa: E402
from chumicro_screens.fonts import Font  # noqa: E402

WIDTH = 32
ROWS = 8


def make_strip(top: int = 8) -> BitmapStrip:
    strip = BitmapStrip(WIDTH, ROWS)
    strip.top = top
    return strip


def row(strip: BitmapStrip, y: int, x_start: int = 0, count: int = WIDTH) -> list:  # noqa: CHU001 - framebuf's own names
    return [strip.bitmap[x, y] for x in range(x_start, x_start + count)]


def test_the_buffer_is_the_bitmap_and_the_font_metrics_are_terminalio() -> None:
    strip = make_strip()
    assert len(strip.buffer) == WIDTH * ROWS * 2
    assert (strip.glyph_width, strip.glyph_height) == (6, 12)


def test_clear_fills_the_strip() -> None:
    strip = make_strip()
    strip.clear(0x1234)
    assert set(row(strip, 0)) == {0x1234}
    assert set(row(strip, ROWS - 1)) == {0x1234}


def test_fill_rect_offsets_by_top_and_clips_past_every_edge() -> None:
    strip = make_strip(top=8)
    strip.fill_rect(2, 10, 3, 2, 7)
    assert row(strip, 2, 0, 6) == [0, 0, 7, 7, 7, 0]
    assert row(strip, 4, 0, 6) == [0] * 6

    strip.fill_rect(-4, 4, 8, 8, 9)
    assert row(strip, 0, 0, 5) == [9, 9, 9, 9, 0]
    assert row(strip, 3, 0, 5) == [9, 9, 9, 9, 7]
    assert row(strip, 4, 0, 5) == [0, 0, 0, 0, 0]

    strip.fill_rect(30, 14, 10, 10, 5)
    assert row(strip, 6, 28, 4) == [0, 0, 5, 5]
    assert row(strip, 7, 28, 4) == [0, 0, 5, 5]

    strip.fill_rect(0, 40, 4, 4, 3)
    assert 3 not in row(strip, 7)


def test_box_draws_the_outline_clipped() -> None:
    strip = make_strip(top=8)
    strip.box(1, 9, 4, 3, 6)
    assert row(strip, 1, 0, 6) == [0, 6, 6, 6, 6, 0]
    assert row(strip, 2, 0, 6) == [0, 6, 0, 0, 6, 0]
    assert row(strip, 3, 0, 6) == [0, 6, 6, 6, 6, 0]
    strip.box(-2, 6, 6, 6, 4)
    assert row(strip, 0, 0, 5) == [0, 0, 0, 4, 0]
    assert row(strip, 3, 0, 5) == [4, 4, 4, 4, 6]


def test_line_offsets_both_ends() -> None:
    strip = make_strip(top=8)
    strip.line(0, 6, 5, 11, 4)
    assert [strip.bitmap[index + 2, index] for index in range(4)] == [4, 4, 4, 4]
    assert strip.bitmap[0, 0] == 0


def test_prepare_ring_cuts_arcs_per_band_and_ring_draws_the_circle_across_bands() -> None:
    """A radius-10 ring at (16, 16) crosses bands 0 to 3 and its four axis points land in them."""
    strip = BitmapStrip(WIDTH, ROWS)
    cache = {}
    strip.prepare_ring(16, 16, 10, cache)

    assert cache[None] == (16, 16, 10, ROWS)
    assert sorted(band for band in cache if band is not None) == [0, 1, 2, 3]
    for band, x, y in ((0, 16, 6), (2, 6, 16), (2, 26, 16), (3, 16, 26)):
        strip.top = band * ROWS
        strip.clear(0)
        strip.ring(16, 16, 10, 5, cache)
        assert strip.bitmap[x, y - strip.top] == 5
    strip.top = 32
    strip.clear(0)
    strip.ring(16, 16, 10, 5, cache)
    assert 5 not in row(strip, 0)


def test_prepare_ring_keeps_arcs_for_the_same_geometry_and_recuts_for_a_move() -> None:
    strip = BitmapStrip(WIDTH, ROWS)
    cache = {}
    strip.prepare_ring(16, 16, 10, cache)
    before = cache[2]
    strip.prepare_ring(16, 16, 10, cache)
    assert cache[2] is before

    strip.prepare_ring(16, 20, 10, cache)
    assert cache[None] == (16, 20, 10, ROWS)
    assert sorted(band for band in cache if band is not None) == [1, 2, 3]


def test_prepare_text_renders_once_per_text_and_text_blits_it_offset() -> None:
    """The synthetic glyph fills its tile one pixel in; the sprite renders at mark time."""
    strip = make_strip(top=8)
    cache = [None, None]
    strip.prepare_text("A", 9, None, cache)
    sprite = cache[1]
    assert (sprite.width, sprite.height) == (6, 12)
    strip.prepare_text("A", 9, None, cache)
    assert cache[1] is sprite

    strip.clear(5)
    strip.text("A", 2, 9, 9, None, cache)
    assert row(strip, 1, 2, 6) == [5, 5, 5, 5, 5, 5]
    assert row(strip, 2, 2, 6) == [5, 9, 9, 9, 9, 5]
    assert row(strip, 7, 2, 6) == [5, 9, 9, 9, 9, 5]


def test_text_in_value_zero_still_shows_through_where_the_glyph_is_clear() -> None:
    strip = make_strip(top=0)
    cache = [None, None]
    strip.prepare_text("A", 0, None, cache)
    strip.clear(5)
    strip.text("A", 0, 0, 0, None, cache)
    assert row(strip, 0, 0, 6) == [5, 5, 5, 5, 5, 5]
    assert row(strip, 1, 0, 6) == [5, 0, 0, 0, 0, 5]


def test_font_text_renders_the_glyphs_into_the_sprite(monkeypatch) -> None:
    monkeypatch.setattr(fonts, "framebuf", None)
    strip = make_strip(top=8)
    font = Font(FontModuleStub())
    cache = [None, None]
    strip.prepare_text("A", 7, font, cache)
    assert (cache[1].width, cache[1].height) == (5, 4)

    strip.text("A", 1, 9, 7, font, cache)
    assert row(strip, 1, 0, 7) == [0, 0, 7, 7, 7, 0, 0]
    assert row(strip, 2, 0, 7) == [0, 7, 0, 0, 0, 7, 0]
    assert row(strip, 3, 0, 7) == [0, 7, 7, 7, 7, 7, 0]


def test_blit_clips_at_every_edge_and_skips_the_key() -> None:
    strip = make_strip(top=8)
    source = DisplayioStub.Bitmap(4, 4, 65536)
    BitmaptoolsStub.fill_region(source, 0, 0, 4, 4, 3)
    source[1, 1] = 0
    strip.clear(5)

    strip.blit(source, -2, 6, 0)
    assert row(strip, 0, 0, 3) == [3, 3, 5]
    assert row(strip, 1, 0, 3) == [3, 3, 5]
    assert strip.bitmap[2, 2] == 5

    strip.blit(source, 30, 13, 0)
    assert row(strip, 5, 29, 3) == [5, 3, 3]
    assert row(strip, 6, 29, 3) == [5, 3, 5]
    assert row(strip, 7, 29, 3) == [5, 3, 3]

    strip.blit(source, 40, 8, 0)
    strip.blit(source, 0, 40, 0)
    assert row(strip, 3, 0, 4) == [5, 5, 5, 5]


def test_blit_without_a_key_copies_every_value() -> None:
    strip = make_strip(top=0)
    source = DisplayioStub.Bitmap(2, 2, 65536)
    source[0, 0] = 0
    source[1, 1] = 8
    strip.clear(5)
    strip.blit(source, 0, 0, -1)
    assert row(strip, 0, 0, 2) == [0, 0]
    assert row(strip, 1, 0, 2) == [0, 8]
