"""CPython-lane tests for the GC9A01A drivers' CircuitPython frame backends.

Seeds ``displayio``, ``bitmaptools``, and ``terminalio`` with the stubs
in ``_circuitpython_stubs`` and swaps the driver's ``framebuf`` binding
to None, which is what a CircuitPython board looks like to it.  The
asserts read the indexes each canvas primitive leaves in the 8-bit
frame, the colors a 16-bit frame holds, and the bytes a flush puts on a
locking bus after the palette passes.  Silicon is covered by the
functional bench.
"""

__chumicro_runtimes__ = ("cpython",)

import sys

from _circuitpython_stubs import BitmaptoolsStub, DisplayioStub, TerminalioStub

sys.modules.setdefault("displayio", DisplayioStub())
sys.modules.setdefault("bitmaptools", BitmaptoolsStub())
sys.modules.setdefault("terminalio", TerminalioStub())

import pytest  # noqa: E402
from chumicro_screens import ScreenService, bitmap_canvas, gc9a01a  # noqa: E402
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
    """A ``busio.SPI`` shape: writes need the lock, it can refuse it, and ``write`` takes bounds.

    ``start`` and ``end`` count the buffer's own items, as the firmware's
    do; the stub bitmaps behind the views count bytes, so here an item
    is a byte.
    """

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

    def write(self, data, *, start=0, end=None):
        assert self.locked, "write outside the lock"
        view = memoryview(data)[start:end]
        self.lengths.append(len(view))
        self.writes.append(bytes(view[:8]))


def run_flush(panel, spi):
    """Drive one flush to its end and return how many strips it put on the bus.

    A one-strip flush and an empty one both end on their first advance,
    so the strips are counted by their memory-write commands.
    """
    base = len(spi.writes)
    flush = panel.flush()
    while True:
        try:
            next(flush)
        except StopIteration:
            break
    return spi.writes[base:].count(b"\x2c")


def make_drained_panel(transfer_rows=60, frame_bits=8):
    """A panel with red at index 7 whose construction-time frame has been flushed."""
    panel, spi, _ = make_panel(transfer_rows=transfer_rows, frame_bits=frame_bits)
    panel.set_color(7, 255, 0, 0)
    run_flush(panel, spi)
    return panel, spi


def make_panel(transfer_rows=None, refusals=0, frame_bits=8):
    spi = FakeBusioSpi(refusals=refusals)
    delays = []
    panel = GC9A01AIndexed(spi, FakePin(), FakePin(), FakePin(),
                           transfer_rows=transfer_rows, frame_bits=frame_bits,
                           sleep_ms=delays.append)
    return panel, spi, delays


def make_full_color_panel(transfer_rows=10):
    spi = FakeBusioSpi()
    delays = []
    panel = GC9A01A(spi, FakePin(), FakePin(), FakePin(),
                    transfer_rows=transfer_rows, sleep_ms=delays.append)
    return panel, spi, delays


def frame_bytes(panel, column, row):
    """The two bytes a 16-bit frame holds for one pixel, as they cross the bus."""
    offset = (row * WIDTH + column) * 2
    return bytes(panel.frame._bitmap[offset:offset + 2])


def swapped(value):
    """The on-wire bytes of a pre-swapped ``color565`` value."""
    return bytes((value & 0xFF, value >> 8))


def first_strip(panel, spi):
    """Run one advance and return the head of the pixel data it put on the bus."""
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    return spi.writes[base + 5]


def test_init_runs_under_the_lock_and_releases_it():
    panel, spi, delays = make_panel()
    assert delays == [5, 20, 150, 120, 20]
    assert spi.writes[0] == b"\xfe"
    assert spi.writes[-1] == b"\x29"
    assert spi.lock_count == 1
    assert spi.unlock_count == 1
    assert not spi.locked


def test_the_default_frame_is_8_bit_in_3_row_strips():
    panel, spi, _ = make_panel()
    bitmap = panel.frame._bitmap
    assert (bitmap.width, bitmap.height, bitmap.bits_per_value) == (WIDTH, HEIGHT, 8)
    assert len(memoryview(bitmap)) == WIDTH * HEIGHT
    assert panel.frame.width == WIDTH
    base = len(spi.writes)
    for _advance in panel.flush():
        pass
    data_lengths = [length for length in spi.lengths[base:] if length > 4]
    assert len(data_lengths) == 80
    assert data_lengths[0] == 3 * ROW_BYTES


def test_frame_bits_16_holds_colors_in_6_row_strips():
    panel, spi, _ = make_panel(frame_bits=16)
    bitmap = panel.frame._bitmap
    assert bitmap.bits_per_value == 16
    assert len(memoryview(bitmap)) == WIDTH * HEIGHT * 2
    base = len(spi.writes)
    for _advance in panel.flush():
        pass
    data_lengths = [length for length in spi.lengths[base:] if length > 4]
    assert len(data_lengths) == 40
    assert data_lengths[0] == 6 * ROW_BYTES


def test_frame_bits_and_transfer_rows_are_validated():
    with raises(ValueError, match="frame_bits"):
        make_panel(frame_bits=12)
    with raises(ValueError, match="transfer_rows"):
        make_panel(transfer_rows=0)
    with raises(ValueError, match="transfer_rows"):
        make_panel(transfer_rows=241)


def test_full_color_frame_is_the_bitmap_itself():
    panel, _, _ = make_full_color_panel()
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


def test_the_8_bit_frame_holds_indexes_and_the_strip_carries_their_colors():
    panel, spi, _ = make_panel(transfer_rows=60)
    panel.set_color(7, 255, 0, 0)
    panel.frame.pixel(0, 0, 7)
    panel.frame.pixel(1, 0, 7)
    assert panel.frame._bitmap[0, 0] == 7
    assert panel.frame.pixel(0, 0) == 7
    assert panel.frame.pixel(2, 0) == 0
    assert panel.frame.pixel(-1, 0) is None
    assert first_strip(panel, spi)[:6] == b"\xf8\x00\xf8\x00\x00\x00"


def test_set_color_after_drawing_recolors_the_8_bit_frame_on_the_next_flush():
    panel, spi, _ = make_panel(transfer_rows=60)
    panel.set_color(5, 255, 0, 0)
    panel.frame.pixel(0, 0, 5)
    assert first_strip(panel, spi)[:2] == b"\xf8\x00"
    panel.set_color(5, 0, 0, 255)
    assert first_strip(panel, spi)[:2] == b"\x00\x1f"


def test_an_advance_of_the_8_bit_frame_leaves_later_strips_correct():
    panel, spi, _ = make_panel(transfer_rows=60)
    panel.set_color(1, 255, 255, 255)
    panel.frame.pixel(0, 0, 1)
    panel.frame.pixel(1, 60, 1)
    panel.frame.pixel(0, 61, 1)
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    next(flush)
    assert spi.writes[base + 5][:4] == b"\xff\xff\x00\x00"
    assert spi.writes[base + 11][:4] == b"\x00\x00\xff\xff"


def test_a_color_below_256_never_masquerades_as_another_index():
    panel, spi, _ = make_panel(transfer_rows=60)
    panel.set_color(3, 255, 0, 0)          # pre-swapped red is 0x00F8, the number 248
    panel.set_color(248, 255, 255, 255)
    panel.frame.pixel(0, 0, 3)
    panel.frame.pixel(1, 0, 248)
    panel.frame.pixel(2, 0, 0)
    assert first_strip(panel, spi)[:6] == b"\xf8\x00\xff\xff\x00\x00"


def test_two_indexes_whose_colors_are_each_other_swap_cleanly():
    panel, spi, _ = make_panel(transfer_rows=60)
    panel.set_color(3, 0, 160, 0)          # pre-swapped value 5
    panel.set_color(5, 0, 96, 0)           # pre-swapped value 3
    assert (panel._colors[3], panel._colors[5]) == (5, 3)
    panel.frame.pixel(0, 0, 3)
    panel.frame.pixel(1, 0, 5)
    assert first_strip(panel, spi)[:4] == b"\x05\x00\x03\x00"


def test_expansion_passes_skip_identities_and_pick_temporaries_no_color_uses():
    palette = [0] * 256
    assigned = bytearray(256)
    assigned[0] = 1
    assert bitmap_canvas.expansion_passes(palette, assigned) == []
    assigned[1] = 1
    palette[1] = 256
    assigned[2] = 1
    palette[2] = 7
    assigned[9] = 1
    palette[9] = 9
    assert bitmap_canvas.expansion_passes(palette, assigned) == [(1, 256), (2, 257), (257, 7)]


def test_16_bit_set_color_after_drawing_applies_to_later_drawing_only():
    panel, _, _ = make_panel(frame_bits=16)
    panel.set_color(5, 255, 0, 0)
    panel.frame.pixel(0, 0, 5)
    panel.set_color(5, 0, 0, 255)
    panel.frame.pixel(1, 0, 5)
    assert frame_bytes(panel, 0, 0) == swapped(color565(255, 0, 0))
    assert frame_bytes(panel, 1, 0) == swapped(color565(0, 0, 255))
    assert panel.frame.pixel(1, 0) == 5


def test_16_bit_strip_is_the_drawn_frame():
    panel, spi, _ = make_panel(transfer_rows=60, frame_bits=16)
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
    canvas.fill(2)
    assert canvas.pixel(239, 239) == 2
    canvas.fill_rect(-10, -10, 20, 20, 3)
    assert canvas.pixel(9, 9) == 3
    assert canvas.pixel(10, 9) == 2
    canvas.fill_rect(235, 235, 50, 50, 3)
    assert canvas.pixel(239, 239) == 3
    canvas.fill_rect(300, 300, 5, 5, 3)


def test_rect_outline_and_the_line_helpers():
    panel, _, _ = make_panel()
    canvas = panel.frame
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


def test_text_places_each_glyph_in_its_index_and_leaves_the_background():
    panel, _, _ = make_panel()
    canvas = panel.frame
    canvas.fill(1)
    canvas.text("AB", 10, 20, 4)
    assert canvas.pixel(11, 21) == 4        # inside the first glyph
    assert canvas.pixel(10, 20) == 1        # the tile's border stays
    assert canvas.pixel(17, 21) == 4        # inside the second glyph
    assert canvas.pixel(16, 21) == 1        # the gap between tiles
    assert canvas.pixel(22, 21) == 1        # past the string


def test_text_in_index_zero_and_index_255_skips_the_background():
    panel, _, _ = make_panel()
    canvas = panel.frame
    canvas.fill(2)
    canvas.text("A", 0, 0, 0)
    assert canvas.pixel(1, 1) == 0
    assert canvas.pixel(0, 0) == 2
    canvas.text("A", 10, 0, 255)
    assert canvas.pixel(11, 1) == 255
    assert canvas.pixel(10, 0) == 2


def test_16_bit_text_in_white_and_black_still_skips_the_background():
    panel, _, _ = make_panel(frame_bits=16)
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
    canvas.text("A", -2, -2, 1)                  # the block spans (-1, -1) to (2, 8)
    assert canvas.pixel(0, 0) == 1
    assert canvas.pixel(2, 3) == 1
    assert canvas.pixel(3, 3) == 0
    canvas.text("éB", 100, 100, 1)
    assert canvas.pixel(101, 101) == 0
    assert canvas.pixel(107, 101) == 1
    canvas.text("A", 238, 238, 1)
    assert canvas.pixel(239, 239) == 1


def test_blit_copies_a_bitmap_of_indexes_in_and_honors_the_key():
    panel, _, _ = make_panel()
    sprite = DisplayioStub.Bitmap(2, 2, 256)
    sprite[0, 0] = 2
    sprite[1, 0] = 1
    sprite[0, 1] = 1
    sprite[1, 1] = 2
    canvas = panel.frame
    canvas.blit(sprite, 5, 5, 2)
    assert canvas.pixel(5, 5) == 0
    assert canvas.pixel(6, 5) == 1
    canvas.blit(sprite, -1, 0)
    assert canvas.pixel(0, 0) == 1
    assert canvas.pixel(0, 1) == 2
    canvas.blit(sprite, 300, 300)


def test_16_bit_blit_copies_colors_in_and_honors_the_key():
    panel, _, _ = make_panel(frame_bits=16)
    panel.set_color(1, 255, 255, 255)
    panel.set_color(2, 255, 0, 0)
    sprite = DisplayioStub.Bitmap(2, 2, 65536)
    sprite[0, 0] = color565(255, 0, 0)
    sprite[1, 0] = color565(255, 255, 255)
    canvas = panel.frame
    canvas.blit(sprite, 5, 5, 2)
    assert canvas.pixel(5, 5) == 0
    assert canvas.pixel(6, 5) == 1


def test_a_new_canvas_is_wholly_dirty_and_each_primitive_records_its_clipped_box():
    panel, _, _ = make_panel()
    canvas = panel.frame
    assert canvas.take_dirty() == (0, 0, WIDTH, HEIGHT)
    assert canvas.take_dirty() == (0, 0, 0, 0)
    canvas.fill_rect(-10, -10, 20, 20, 3)
    assert canvas.take_dirty() == (0, 0, 10, 10)
    canvas.pixel(30, 40, 1)
    canvas.pixel(-1, 0, 1)
    assert canvas.take_dirty() == (30, 40, 31, 41)
    assert canvas.pixel(30, 40) == 1
    assert canvas.take_dirty() == (0, 0, 0, 0)
    canvas.line(9, 9, 3, 5, 1)
    assert canvas.take_dirty() == (3, 5, 10, 10)
    canvas.ellipse(120, 120, 10, 10, 1)
    assert canvas.take_dirty() == (110, 110, 131, 131)
    canvas.ellipse(2, 2, 6, 6, 1)
    assert canvas.take_dirty() == (0, 0, 9, 9)
    canvas.poly(100, 100, [0, 0, 4, 0, 4, 4], 1)
    assert canvas.take_dirty() == (100, 100, 105, 105)
    canvas.rect(50, 50, 4, 3, 1)
    assert canvas.take_dirty() == (50, 50, 54, 53)
    canvas.fill(2)
    assert canvas.take_dirty() == (0, 0, WIDTH, HEIGHT)


def test_text_blit_and_dirty_record_their_boxes():
    panel, _, _ = make_panel()
    canvas = panel.frame
    canvas.take_dirty()
    canvas.text("AB", 10, 20, 4)
    assert canvas.take_dirty() == (10, 20, 22, 32)
    canvas.text("A", 238, 238, 1)
    assert canvas.take_dirty() == (238, 238, WIDTH, HEIGHT)
    sprite = DisplayioStub.Bitmap(2, 2, 256)
    canvas.blit(sprite, 5, 5)
    assert canvas.take_dirty() == (5, 5, 7, 7)
    canvas.blit(sprite, -1, 239)
    assert canvas.take_dirty() == (0, 239, 1, HEIGHT)
    canvas.blit(sprite, 300, 300)
    assert canvas.take_dirty() == (0, 0, 0, 0)
    canvas.dirty(200, 200, 100, 100)
    assert canvas.take_dirty() == (200, 200, WIDTH, HEIGHT)


def test_a_flush_with_nothing_drawn_ends_at_once_with_no_bus_traffic():
    panel, spi = make_drained_panel()
    base = len(spi.writes)
    assert run_flush(panel, spi) == 0
    assert len(spi.writes) == base
    assert spi.lock_count == spi.unlock_count


def test_the_8_bit_flush_sends_the_touched_strip_one_row_write_per_dirty_row():
    panel, spi = make_drained_panel()
    panel.frame.vline(100, 120, 11, 7)
    base = len(spi.writes)
    locks = spi.lock_count
    assert run_flush(panel, spi) == 1
    strip = spi.writes[base:]
    assert len(strip) == 5 + 60
    assert strip[1] == b"\x00\x64\x00\x64"
    assert strip[3] == b"\x00\x78\x00\xb3"
    assert spi.lengths[base + 5:base + 65] == [2] * 60
    assert strip[5] == b"\xf8\x00"
    assert strip[15] == b"\xf8\x00"
    assert strip[16] == b"\x00\x00"
    assert spi.lock_count == locks + 1
    assert not spi.locked


def test_the_8_bit_flush_sends_a_full_width_band_as_whole_strips():
    panel, spi = make_drained_panel()
    panel.frame.fill_rect(0, 55, WIDTH, 10, 7)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 2
    assert spi.writes[base + 1] == b"\x00\x00\x00\xef"
    assert spi.writes[base + 3] == b"\x00\x00\x00\x3b"
    assert spi.lengths[base + 5] == 60 * ROW_BYTES
    assert spi.writes[base + 9] == b"\x00\x3c\x00\x77"
    assert spi.lengths[base + 11] == 60 * ROW_BYTES


def test_the_16_bit_flush_windows_its_rows_from_the_frame():
    panel, spi = make_drained_panel(frame_bits=16)
    panel.frame.pixel(10, 0, 7)
    panel.frame.pixel(12, 0, 1)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 1
    assert spi.writes[base + 1] == b"\x00\x0a\x00\x0c"
    assert spi.writes[base + 3] == b"\x00\x00\x00\x3b"
    assert spi.lengths[base + 5:base + 65] == [6] * 60
    assert spi.writes[base + 5] == b"\xf8\x00\x00\x00\x00\x00"
    assert spi.writes[base + 6] == b"\x00\x00\x00\x00\x00\x00"


def test_set_color_marks_the_8_bit_frame_and_leaves_the_16_bit_frame_clean():
    panel, spi = make_drained_panel()
    panel.set_color(7, 0, 255, 0)
    assert run_flush(panel, spi) == 4
    panel, spi = make_drained_panel(frame_bits=16)
    panel.set_color(7, 0, 255, 0)
    assert run_flush(panel, spi) == 0


def test_a_preallocated_bitmap_becomes_the_frame_on_either_depth():
    spi = FakeBusioSpi()
    frame = DisplayioStub.Bitmap(WIDTH, HEIGHT, 65536)
    panel = GC9A01AIndexed(spi, FakePin(), FakePin(), FakePin(), frame_bits=16,
                           bitmap=frame, sleep_ms=lambda ms: None)
    assert panel.frame._bitmap is frame
    panel.set_color(1, 255, 255, 255)
    panel.frame.pixel(0, 0, 1)
    assert frame[0, 0] == 0xFFFF
    indexes = DisplayioStub.Bitmap(WIDTH, HEIGHT, 256)
    panel = GC9A01AIndexed(spi, FakePin(), FakePin(), FakePin(), bitmap=indexes,
                           sleep_ms=lambda ms: None)
    assert panel.frame._bitmap is indexes
    full_color = GC9A01A(spi, FakePin(), FakePin(), FakePin(), bitmap=frame,
                         sleep_ms=lambda ms: None)
    assert full_color.frame is frame


def test_a_preallocated_bitmap_of_the_wrong_shape_is_refused():
    spi = FakeBusioSpi()
    with raises(ValueError, match="240 by 240"):
        GC9A01AIndexed(spi, FakePin(), FakePin(), FakePin(), frame_bits=16,
                       bitmap=DisplayioStub.Bitmap(128, 64, 65536), sleep_ms=lambda ms: None)
    with raises(ValueError, match="frame_bits"):
        GC9A01AIndexed(spi, FakePin(), FakePin(), FakePin(), frame_bits=8,
                       bitmap=DisplayioStub.Bitmap(WIDTH, HEIGHT, 65536), sleep_ms=lambda ms: None)
    with raises(ValueError, match="frame_bits"):
        GC9A01A(spi, FakePin(), FakePin(), FakePin(),
                bitmap=DisplayioStub.Bitmap(WIDTH, HEIGHT, 256), sleep_ms=lambda ms: None)


def test_a_partial_flush_under_screen_service_takes_only_its_strips_worth_of_handles():
    panel, spi = make_drained_panel()
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    panel.frame.fill_rect(20, 100, 50, 61, 7)
    service.show()
    for tick in range(2):
        assert service.check(tick) is True
        service.handle(tick)
    assert service.check(3) is False
    assert panel.frame.take_dirty() == (0, 0, 0, 0)
