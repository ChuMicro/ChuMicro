"""CPython-lane tests for ``Font`` rendering sprites on CircuitPython.

Seeds ``displayio``, ``bitmaptools``, and ``terminalio`` with the stubs
in ``_circuitpython_stubs`` and binds the font module's ``framebuf`` to
None, which is what a CircuitPython board looks like to it, so ``Font``
builds its glyph sheet and ``render`` stamps a string into a sprite.
Every assert reads pixel values back from the sprite.  Silicon is
covered by the functional bench.
"""

__chumicro_runtimes__ = ("cpython",)

import sys

from _circuitpython_stubs import BitmaptoolsStub, DisplayioStub, TerminalioStub

sys.modules.setdefault("displayio", DisplayioStub())
sys.modules.setdefault("bitmaptools", BitmaptoolsStub())
sys.modules.setdefault("terminalio", TerminalioStub())

import pytest  # noqa: E402
from _font_stubs import FontModuleStub  # noqa: E402
from chumicro_screens import fonts  # noqa: E402
from chumicro_screens.fonts import Font  # noqa: E402


@pytest.fixture(autouse=True)
def _no_framebuf(monkeypatch):
    monkeypatch.setattr(fonts, "framebuf", None)


def row(sprite, y, count):  # noqa: CHU001 - framebuf's own names
    return [sprite[x, y] for x in range(count)]


def test_metrics_and_widths_match_the_framebuf_lane():
    font = Font(FontModuleStub())
    assert (font.height, font.baseline, font.max_width) == (4, 3, 9)
    assert font.width("AB") == 14
    assert font.width("Z") == 3


def test_render_stamps_each_glyph_in_the_value_over_the_key():
    sprite = Font(FontModuleStub()).render("AC", 7, 65536, 0)
    assert (sprite.width, sprite.height) == (8, 4)
    assert row(sprite, 0, 8) == [0, 7, 7, 7, 0, 7, 7, 7]
    assert row(sprite, 1, 8) == [7, 0, 0, 0, 7, 7, 0, 0]
    assert row(sprite, 2, 8) == [7, 7, 7, 7, 7, 7, 0, 0]
    assert row(sprite, 3, 8) == [7, 0, 0, 0, 7, 7, 7, 7]


def test_render_in_value_zero_puts_the_key_behind_the_glyph():
    sprite = Font(FontModuleStub()).render("A", 0, 65536, 0xFFFF)
    assert row(sprite, 0, 5) == [0xFFFF, 0, 0, 0, 0xFFFF]
    assert row(sprite, 1, 5) == [0, 0xFFFF, 0xFFFF, 0xFFFF, 0]


def test_a_reversed_module_renders_the_same_glyphs():
    forward = Font(FontModuleStub()).render("B", 1, 65536, 0)
    reversed_bits = Font(FontModuleStub(reverse=True)).render("B", 1, 65536, 0)
    assert row(forward, 0, 9) == row(reversed_bits, 0, 9) == [1] * 9
    assert row(forward, 1, 9) == row(reversed_bits, 1, 9) == [1, 0, 0, 0, 0, 0, 0, 0, 1]


def test_unknown_characters_render_the_substitute_glyph():
    sprite = Font(FontModuleStub()).render("Z", 3, 65536, 0)
    assert (sprite.width, sprite.height) == (3, 4)
    assert row(sprite, 0, 3) == [3, 3, 3]
    assert row(sprite, 1, 3) == [3, 0, 0]
