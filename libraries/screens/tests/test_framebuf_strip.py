"""Host-lane tests for ``FramebufStrip``, the MicroPython strip canvas.

Runs on CPython and both unix ports.  Where the runtime ships
``framebuf`` (the MicroPython port) the real C primitives draw, which
is the path a board takes; elsewhere the shared stub stands in.  The
asserts read the pixels each primitive leaves in a strip whose ``top``
is not zero, which is where the row offset matters.
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
from chumicro_screens.framebuf_strip import FramebufStrip  # noqa: E402

WIDTH = 16
ROWS = 8


def make_strip(top: int = 8) -> tuple:
    """An 8-bit strip over a fresh buffer with its row 0 at panel row ``top``."""
    buffer = bytearray(WIDTH * ROWS)
    strip = FramebufStrip(framebuf.FrameBuffer(buffer, WIDTH, ROWS, framebuf.GS8),
                          WIDTH, ROWS, framebuf.GS8)
    strip.top = top
    return strip, buffer


def row(buffer: bytearray, y: int) -> list:  # noqa: CHU001 - framebuf's own names
    return list(buffer[y * WIDTH:(y + 1) * WIDTH])


def test_clear_fills_the_strip() -> None:
    strip, buffer = make_strip()
    strip.clear(5)
    assert set(buffer) == {5}


def test_fill_rect_lands_at_the_panel_row_less_top_and_clips() -> None:
    """Rows 10 to 12 of the panel are rows 2 to 4 of a strip whose top is 8."""
    strip, buffer = make_strip(top=8)
    strip.fill_rect(2, 10, 3, 2, 7)
    assert row(buffer, 1) == [0] * WIDTH
    assert row(buffer, 2)[:6] == [0, 0, 7, 7, 7, 0]
    assert row(buffer, 3)[:6] == [0, 0, 7, 7, 7, 0]
    assert row(buffer, 4) == [0] * WIDTH

    strip.fill_rect(14, 14, 10, 10, 9)
    assert row(buffer, 6)[13:] == [0, 9, 9]
    assert row(buffer, 7)[13:] == [0, 9, 9]


def test_box_draws_the_outline_only() -> None:
    strip, buffer = make_strip(top=8)
    strip.box(1, 9, 4, 3, 6)
    assert row(buffer, 1)[:6] == [0, 6, 6, 6, 6, 0]
    assert row(buffer, 2)[:6] == [0, 6, 0, 0, 6, 0]
    assert row(buffer, 3)[:6] == [0, 6, 6, 6, 6, 0]


def test_line_offsets_both_ends() -> None:
    strip, buffer = make_strip(top=8)
    strip.line(0, 8, 3, 11, 4)
    assert [row(buffer, index)[index] for index in range(4)] == [4, 4, 4, 4]
    assert row(buffer, 4)[4] == 0


def test_ring_draws_the_part_of_the_circle_inside_the_strip() -> None:
    """A radius-4 ring centered two rows below the strip shows its top arc and nothing of its bottom."""
    strip, buffer = make_strip(top=8)
    strip.ring(8, 18, 4, 3, {})
    assert row(buffer, 6)[8] == 3
    assert row(buffer, 7)[8] == 0
    assert row(buffer, 0) == [0] * WIDTH


def test_prepare_ring_and_prepare_text_touch_nothing() -> None:
    strip, _ = make_strip()
    cache = {}
    strip.prepare_ring(8, 8, 4, cache)
    text_cache = [None, None]
    strip.prepare_text("x", 1, None, text_cache)
    assert cache == {}
    assert text_cache == [None, None]


def test_built_in_text_lands_at_the_panel_row_less_top() -> None:
    """A character at panel row 8 lands in strip rows 0 to 7 (a cell in the stub, a glyph in framebuf)."""
    strip, buffer = make_strip(top=8)
    strip.text("A", 4, 8, 2, None, [None, None])
    assert any(value == 2 for value in row(buffer, 3)[4:12])
    assert row(buffer, 3)[:4] == [0, 0, 0, 0]
    assert row(buffer, 3)[12:] == [0, 0, 0, 0]


def test_font_text_blits_glyphs_through_the_font() -> None:
    """The stub font's ``A`` lands with its rows offset by the strip's top."""
    strip, buffer = make_strip(top=8)
    strip.text("A", 1, 9, 7, Font(FontModuleStub()), [None, None])
    assert row(buffer, 1)[:7] == [0, 0, 7, 7, 7, 0, 0]
    assert row(buffer, 2)[:7] == [0, 7, 0, 0, 0, 7, 0]
    assert row(buffer, 3)[:7] == [0, 7, 7, 7, 7, 7, 0]


def test_blit_offsets_the_source_and_skips_the_key() -> None:
    strip, buffer = make_strip(top=8)
    source_buffer = bytearray((1, 0, 1, 0))
    source = framebuf.FrameBuffer(source_buffer, 2, 2, framebuf.GS8)
    strip.clear(5)
    strip.blit(source, 3, 9, 0)
    assert row(buffer, 1)[3:5] == [1, 5]
    assert row(buffer, 2)[3:5] == [1, 5]
