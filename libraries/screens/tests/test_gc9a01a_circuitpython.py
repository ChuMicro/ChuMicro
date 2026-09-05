"""CPython-lane tests for the GC9A01A drivers' CircuitPython frame backend.

Seeds ``displayio``, ``bitmaptools``, and ``terminalio`` with the stubs
in ``_circuitpython_stubs`` and swaps the driver's ``framebuf`` binding
to None, which is what a CircuitPython board looks like to it.  The
asserts read the bytes each canvas primitive leaves in the 16-bit
frame and the bytes a flush puts on a locking bus.  Silicon is covered
by the functional bench.
"""

__chumicro_runtimes__ = ("cpython",)

import sys

from _circuitpython_stubs import BitmaptoolsStub, DisplayioStub, TerminalioStub

sys.modules.setdefault("displayio", DisplayioStub())
sys.modules.setdefault("bitmaptools", BitmaptoolsStub())
sys.modules.setdefault("terminalio", TerminalioStub())

import pytest  # noqa: E402
from chumicro_screens import ScreenService, gc9a01a  # noqa: E402
from chumicro_screens.bitmap_canvas import BitmapCanvas  # noqa: E402
from chumicro_screens.gc9a01a import GC9A01A, GC9A01AIndexed, color565  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402
from chumicro_timing.testing import FakeTicks  # noqa: E402

WIDTH = 240
HEIGHT = 240
ROW_BYTES = WIDTH * 2


@pytest.fixture(autouse=True)
def _no_framebuf(monkeypatch):
    monkeypatch.setattr(gc9a01a, "framebuf", None)


class FakePin:
    def __init__(self):
        self.states = []

    def __call__(self, value):
        self.states.append(value)


class FakeBusioSpi:
    """A ``busio.SPI`` shape: writes need the lock, and it can refuse it."""

    def __init__(self, refusals=0):
        self.refusals = refusals
        self.locked = False
        self.lock_count = 0
        self.unlock_count = 0
        self.writes = []
        self.lengths = []

    def try_lock(self):
        self.lock_count += 1
        if self.refusals:
            self.refusals -= 1
            return False
        self.locked = True
        return True

    def unlock(self):
        self.unlock_count += 1
        self.locked = False

    def write(self, data):
        assert self.locked, "write outside the lock"
        self.lengths.append(len(data))
        self.writes.append(bytes(data[:8]))


def make_panel(panel_class=GC9A01AIndexed, transfer_rows=6, refusals=0):
    spi = FakeBusioSpi(refusals=refusals)
    delays = []
    panel = panel_class(spi, FakePin(), FakePin(), FakePin(),
                        transfer_rows=transfer_rows, sleep_ms=delays.append)
    return panel, spi, delays


def frame_bytes(panel, column, row):
    """The two bytes the frame holds for one pixel, as they cross the bus."""
    if isinstance(panel.frame, BitmapCanvas):
        bitmap = panel.frame._bitmap
    else:
        bitmap = panel.frame
    offset = (row * WIDTH + column) * 2
    return bytes(bitmap[offset:offset + 2])


def swapped(value):
    """The on-wire bytes of a pre-swapped ``color565`` value."""
    return bytes((value & 0xFF, value >> 8))


def test_init_runs_under_the_lock_and_releases_it():
    panel, spi, delays = make_panel()
    assert delays == [5, 20, 150, 120, 20]
    assert spi.writes[0] == b"\xfe"
    assert spi.writes[-1] == b"\x29"
    assert spi.lock_count == 1
    assert spi.unlock_count == 1
    assert not spi.locked


def test_indexed_frame_is_a_16_bit_bitmap_the_size_of_the_panel():
    panel, _, _ = make_panel()
    bitmap = panel.frame._bitmap
    assert (bitmap.width, bitmap.height) == (WIDTH, HEIGHT)
    assert len(memoryview(bitmap)) == WIDTH * HEIGHT * 2
    assert panel.frame.width == WIDTH


def test_full_color_frame_is_the_bitmap_itself():
    panel, _, _ = make_panel(GC9A01A, transfer_rows=10)
    assert panel.frame.width == WIDTH
    assert len(memoryview(panel.frame)) == WIDTH * HEIGHT * 2


def test_each_advance_locks_sends_a_windowed_strip_and_unlocks():
    panel, spi, _ = make_panel(transfer_rows=60)
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    strip = spi.writes[base:]
    assert strip[0] == b"\x2a"
    assert strip[1] == b"\x00\x00\x00\xef"
    assert strip[2] == b"\x2b"
    assert strip[3] == b"\x00\x00\x00\x3b"
    assert strip[4] == b"\x2c"
    assert spi.lengths[base + 5] == 60 * ROW_BYTES
    assert spi.lock_count == 2
    assert spi.unlock_count == 2
    assert not spi.locked


def test_a_busy_bus_is_retried_until_the_lock_is_granted():
    panel, spi, _ = make_panel(transfer_rows=60, refusals=3)
    flush = panel.flush()
    next(flush)
    assert spi.lock_count == 2 + 3
    assert spi.unlock_count == 2


def test_a_frame_is_strips_many_advances_and_bus_bytes():
    panel, spi, _ = make_panel(transfer_rows=100)
    base = len(spi.writes)
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    service.show()
    for tick in range(3):
        assert service.check(tick) is True
        service.handle(tick)
    assert service.check(4) is False
    data_lengths = [length for length in spi.lengths[base:] if length > 4]
    assert data_lengths == [100 * ROW_BYTES, 100 * ROW_BYTES, 40 * ROW_BYTES]


def test_set_color_then_pixel_puts_the_swapped_color_in_the_frame():
    panel, spi, _ = make_panel()
    panel.set_color(7, 255, 0, 0)
    panel.frame.pixel(3, 2, 7)
    assert frame_bytes(panel, 3, 2) == b"\xf8\x00"
    assert panel.frame.pixel(3, 2) == 7
    assert panel.frame.pixel(4, 2) == 0
    assert panel.frame.pixel(-1, 2) is None


def test_set_color_after_drawing_applies_to_later_drawing_only():
    panel, _, _ = make_panel()
    panel.set_color(5, 255, 0, 0)
    panel.frame.pixel(0, 0, 5)
    panel.set_color(5, 0, 0, 255)
    panel.frame.pixel(1, 0, 5)
    assert frame_bytes(panel, 0, 0) == swapped(color565(255, 0, 0))
    assert frame_bytes(panel, 1, 0) == swapped(color565(0, 0, 255))


def test_the_strip_sent_is_the_drawn_frame():
    panel, spi, _ = make_panel(transfer_rows=60)
    panel.set_color(1, 255, 255, 255)
    panel.frame.pixel(0, 0, 1)
    panel.frame.pixel(1, 60, 1)
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    next(flush)
    assert spi.writes[base + 5][:2] == b"\xff\xff"
    assert spi.writes[base + 11][2:4] == b"\xff\xff"


def test_fill_and_fill_rect_clip_to_the_frame():
    panel, _, _ = make_panel()
    canvas = panel.frame
    panel.set_color(2, 0, 255, 0)
    canvas.fill(2)
    assert frame_bytes(panel, 239, 239) == swapped(color565(0, 255, 0))
    panel.set_color(3, 0, 0, 255)
    canvas.fill_rect(-10, -10, 20, 20, 3)
    assert frame_bytes(panel, 9, 9) == swapped(color565(0, 0, 255))
    assert frame_bytes(panel, 10, 9) == swapped(color565(0, 255, 0))
    canvas.fill_rect(235, 235, 50, 50, 3)
    assert frame_bytes(panel, 239, 239) == swapped(color565(0, 0, 255))
    canvas.fill_rect(300, 300, 5, 5, 3)


def test_rect_outline_and_the_line_helpers():
    panel, _, _ = make_panel()
    canvas = panel.frame
    panel.set_color(1, 255, 255, 255)
    canvas.rect(10, 10, 5, 4, 1)
    assert canvas.pixel(10, 10) == 1
    assert canvas.pixel(14, 13) == 1
    assert canvas.pixel(12, 11) == 0
    canvas.rect(20, 20, 3, 3, 1, True)
    assert canvas.pixel(21, 21) == 1
    canvas.hline(30, 30, 4, 1)
    canvas.vline(40, 40, 4, 1)
    assert canvas.pixel(33, 30) == 1
    assert canvas.pixel(34, 30) == 0
    assert canvas.pixel(40, 43) == 1
    assert canvas.pixel(40, 44) == 0


def test_line_and_circle_and_polygon_draw_through_bitmaptools():
    panel, _, _ = make_panel()
    canvas = panel.frame
    panel.set_color(1, 255, 255, 255)
    canvas.line(0, 0, 3, 3, 1)
    assert canvas.pixel(2, 2) == 1
    canvas.ellipse(120, 120, 10, 10, 1)
    assert canvas.pixel(130, 120) == 1
    assert canvas.pixel(120, 120) == 0
    canvas.poly(100, 100, [0, 0, 4, 0, 4, 4], 1)
    assert canvas.pixel(102, 100) == 1
    assert canvas.pixel(104, 102) == 1
    assert canvas.pixel(102, 102) == 1


def test_shapes_without_a_c_path_are_refused():
    panel, _, _ = make_panel()
    with raises(ValueError, match="circle"):
        panel.frame.ellipse(120, 120, 10, 20, 1)
    with raises(ValueError, match="circle"):
        panel.frame.ellipse(120, 120, 10, 10, 1, True)
    with raises(ValueError, match="outline"):
        panel.frame.poly(0, 0, [0, 0, 4, 0, 4, 4], 1, True)


def test_text_places_each_glyph_in_its_color_and_leaves_the_background():
    panel, _, _ = make_panel()
    canvas = panel.frame
    panel.set_color(1, 255, 255, 255)
    panel.set_color(4, 255, 128, 0)
    canvas.fill(1)
    canvas.text("AB", 10, 20, 4)
    orange = swapped(color565(255, 128, 0))
    white = swapped(color565(255, 255, 255))
    assert frame_bytes(panel, 11, 21) == orange       # inside the first glyph
    assert frame_bytes(panel, 10, 20) == white        # the tile's border stays
    assert frame_bytes(panel, 17, 21) == orange       # inside the second glyph
    assert frame_bytes(panel, 16, 21) == white        # the gap between tiles
    assert frame_bytes(panel, 22, 21) == white        # past the string


def test_text_in_white_and_black_still_skips_the_background():
    panel, _, _ = make_panel()
    canvas = panel.frame
    panel.set_color(1, 255, 255, 255)
    panel.set_color(2, 0, 255, 0)
    canvas.fill(2)
    canvas.text("A", 0, 0, 1)
    assert frame_bytes(panel, 1, 1) == b"\xff\xff"
    assert frame_bytes(panel, 0, 0) == swapped(color565(0, 255, 0))
    canvas.text("A", 10, 0, 0)
    assert frame_bytes(panel, 11, 1) == b"\x00\x00"
    assert frame_bytes(panel, 10, 0) == swapped(color565(0, 255, 0))


def test_text_clips_at_the_frame_edges_and_skips_unknown_glyphs():
    panel, _, _ = make_panel()
    canvas = panel.frame
    panel.set_color(1, 255, 255, 255)
    canvas.text("A", -2, -2, 1)                  # the block spans (-1, -1) to (2, 8)
    assert canvas.pixel(0, 0) == 1
    assert canvas.pixel(2, 3) == 1
    assert canvas.pixel(3, 3) == 0
    canvas.text("éB", 100, 100, 1)
    assert canvas.pixel(101, 101) == 0
    assert canvas.pixel(107, 101) == 1
    canvas.text("A", 238, 238, 1)
    assert canvas.pixel(239, 239) == 1


def test_blit_copies_a_canvas_in_and_honors_the_key():
    panel, _, _ = make_panel()
    panel.set_color(1, 255, 255, 255)
    panel.set_color(2, 255, 0, 0)
    sprite = DisplayioStub.Bitmap(2, 2, 65536)
    sprite[0, 0] = color565(255, 0, 0)
    sprite[1, 0] = color565(255, 255, 255)
    sprite[0, 1] = color565(255, 255, 255)
    sprite[1, 1] = color565(255, 0, 0)
    canvas = panel.frame
    canvas.blit(sprite, 5, 5, 2)
    assert canvas.pixel(5, 5) == 0
    assert canvas.pixel(6, 5) == 1
    canvas.blit(sprite, -1, 0)
    assert canvas.pixel(0, 0) == 1
    assert canvas.pixel(0, 1) == 2
    canvas.blit(sprite, 300, 300)
