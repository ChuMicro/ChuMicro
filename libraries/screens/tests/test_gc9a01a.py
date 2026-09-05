"""Host-lane tests for the GC9A01A panel drivers.

Runs on CPython and the unix ports through host fakes; silicon is
covered by the functional bench.  The shared framebuf stub seeded
below satisfies the module-load import on runtimes that do not ship
framebuf.
"""

__chumicro_host_only__ = True

import sys

from _screen_stubs import FramebufStub

sys.modules.setdefault("framebuf", FramebufStub())

from chumicro_screens import ScreenService  # noqa: E402
from chumicro_screens.gc9a01a import GC9A01A, GC9A01AIndexed, color565  # noqa: E402
from chumicro_test_harness import raises, skip  # noqa: E402
from chumicro_timing.testing import FakeTicks  # noqa: E402


def _skip_unless_frame_buffer_headroom() -> None:
    """Loud-skip on heaps that cannot hold the full-color frame buffer."""
    try:
        import gc

        free = gc.mem_free()
    except (ImportError, AttributeError):
        return  # CPython has no gc.mem_free; run the test.
    if free < 400_000:
        skip(
            "GC9A01A owns a 115,200 B RGB565 frame buffer; exceeds "
            "264 KB-board headroom (intrinsic allocation); validated "
            "on PSRAM + CPython",
        )


def _skip_unless_indexed_headroom() -> None:
    """Loud-skip on heaps that cannot hold the indexed frame plus a 100-row strip."""
    try:
        import gc

        free = gc.mem_free()
    except (ImportError, AttributeError):
        return  # CPython has no gc.mem_free; run the test.
    if free < 128_000:
        skip(
            "GC9A01AIndexed tests need the 57,600 B frame plus up to "
            "33,600 B of strip buffer; this host lane's heap is smaller, "
            "and the bench validates the driver on a 264 KB board",
        )


class FakePin:
    """Records every level the driver drives onto the pin."""

    def __init__(self) -> None:
        self.states: list[int] = []

    def __call__(self, value: int) -> None:
        self.states.append(value)


class FakeSpi:
    """Records each write's length and its first eight bytes.

    Whole strips would hold hundreds of kilobytes across a frame, more
    than the boards the indexed driver targets can spare, and every
    assertion below reads window bytes, lengths, or a strip's head.
    """

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.lengths: list[int] = []

    def write(self, data: object) -> None:
        self.lengths.append(len(data))
        self.writes.append(bytes(data[:8]))


class DelayRecorder:
    """Records requested sleeps instead of sleeping."""

    def __init__(self) -> None:
        self.delays: list[int] = []

    def __call__(self, duration_ms: int) -> None:
        self.delays.append(duration_ms)


def make_panel(panel_class: object = GC9A01A, transfer_rows: int = 10) -> tuple:
    spi = FakeSpi()
    reset = FakePin()
    delays = DelayRecorder()
    panel = panel_class(spi, FakePin(), FakePin(), reset,
                        transfer_rows=transfer_rows, sleep_ms=delays)
    return panel, spi, delays, reset


def run_flush(panel: object, spi: FakeSpi) -> int:
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


def make_drained_indexed_panel(transfer_rows: int = 60) -> tuple:
    """An indexed panel with red at index 7 whose construction-time frame has been flushed."""
    panel, spi, _delays, _reset = make_panel(GC9A01AIndexed, transfer_rows=transfer_rows)
    panel.set_color(7, 255, 0, 0)
    run_flush(panel, spi)
    return panel, spi


def test_construction_resets_then_inits() -> None:
    """Reset pulses 1-0-1 with the datasheet delays, then the init runs."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel()
    assert reset.states == [1, 0, 1]
    assert delays.delays == [5, 20, 150, 120, 20]
    assert spi.writes[0] == b"\xfe"
    assert spi.writes[1] == b"\xef"
    assert spi.writes[-1] == b"\x29"
    pixel_format_index = spi.writes.index(b"\x3a")
    assert spi.writes[pixel_format_index + 1] == b"\x05"
    assert len(spi.writes) == 34
    assert panel.width == 240
    assert panel.height == 240
    assert panel.frame is not None


def test_transfer_rows_bounds() -> None:
    """transfer_rows outside 1..240 is refused by both drivers."""
    for panel_class in (GC9A01A, GC9A01AIndexed):
        with raises(ValueError):
            make_panel(panel_class, transfer_rows=0)
        with raises(ValueError):
            make_panel(panel_class, transfer_rows=241)


def test_a_preallocated_bitmap_is_refused_where_framebuf_owns_the_frame() -> None:
    """Both drivers raise ValueError naming CircuitPython when bitmap is passed on the framebuf path."""
    for panel_class in (GC9A01A, GC9A01AIndexed):
        with raises(ValueError, match="CircuitPython"):
            panel_class(FakeSpi(), FakePin(), FakePin(), FakePin(), bitmap=bytearray(4),
                        sleep_ms=DelayRecorder())


def test_flush_sends_self_contained_strips() -> None:
    """Each advance writes window commands plus that strip's rows."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=60)
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    strip = spi.writes[base:]
    assert strip[0] == b"\x2a"
    assert strip[1] == b"\x00\x00\x00\xef"
    assert strip[2] == b"\x2b"
    assert strip[3] == b"\x00\x00\x00\x3b"
    assert strip[4] == b"\x2c"
    assert spi.lengths[base + 5] == 60 * 480
    next(flush)
    assert spi.writes[base + 9] == b"\x00\x3c\x00\x77"


def test_flush_advance_count_and_completion() -> None:
    """A 60-row strip frame yields three times, and every strip is six writes."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=60)
    base = len(spi.writes)
    flush = panel.flush()
    yields = 0
    while True:
        try:
            next(flush)
        except StopIteration:
            break
        yields += 1
    assert yields == 3
    assert len(spi.writes) - base == 4 * 6


def test_partial_last_strip() -> None:
    """240 rows in 100-row strips ends with a 40-row strip."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=100)
    base = len(spi.writes)
    flush = panel.flush()
    while True:
        try:
            next(flush)
        except StopIteration:
            break
    data_lengths = [length for length in spi.lengths[base:] if length > 4]
    assert data_lengths == [100 * 480, 100 * 480, 40 * 480]
    assert spi.writes[base + 15] == b"\x00\xc8\x00\xef"


def test_strip_data_comes_from_the_frame_buffer() -> None:
    """Strip N carries the buffer bytes for its rows, in the order stored."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=60)
    panel._buffer[0] = 0xAB
    panel._buffer[60 * 480] = 0xCD
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    next(flush)
    assert spi.writes[base + 5][0] == 0xAB
    assert spi.writes[base + 11][0] == 0xCD


def test_full_color_flush_sends_only_the_strips_covering_the_drawn_rows() -> None:
    """After a first frame, a line on row 130 sends the 60-row strip holding it and nothing else."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=60)
    run_flush(panel, spi)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 0
    assert len(spi.writes) == base
    panel.frame.hline(0, 130, 240, color565(255, 0, 0))
    assert run_flush(panel, spi) == 1
    assert spi.writes[base + 1] == b"\x00\x00\x00\xef"
    assert spi.writes[base + 3] == b"\x00\x78\x00\xb3"
    assert spi.lengths[base + 5] == 60 * 480


def test_frame_completes_under_screen_service() -> None:
    """ScreenService drives one frame to done in strips-many handles."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=60)
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    base = len(spi.writes)
    service.show()
    for tick in range(4):
        assert service.check(tick) is True
        service.handle(tick)
    assert service.check(5) is False
    assert len(spi.writes) - base == 4 * 6


def test_color565_packs_channels_in_bus_byte_order() -> None:
    """Primaries pack to RGB565 pre-swapped for the panel's byte order."""
    assert color565(255, 0, 0) == 0x00F8
    assert color565(0, 255, 0) == 0xE007
    assert color565(0, 0, 255) == 0x1F00
    assert color565(255, 255, 255) == 0xFFFF
    assert color565(0, 0, 0) == 0x0000


def test_indexed_construction_resets_then_inits() -> None:
    """Reset and init match the full-color driver; the frame is 8-bit."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_panel(GC9A01AIndexed)
    assert reset.states == [1, 0, 1]
    assert delays.delays == [5, 20, 150, 120, 20]
    assert spi.writes[0] == b"\xfe"
    assert spi.writes[-1] == b"\x29"
    assert len(spi.writes) == 34
    assert len(panel._buffer) == 240 * 240
    assert panel.width == 240
    assert panel.height == 240


def test_indexed_flush_expands_through_the_palette() -> None:
    """Drawn indexes leave the bus as their palette's RGB565 bytes."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_panel(GC9A01AIndexed, transfer_rows=60)
    panel.set_color(7, 255, 0, 0)
    panel.frame.pixel(0, 0, 7)
    panel.frame.pixel(1, 0, 7)
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    strip = spi.writes[base:]
    assert strip[0] == b"\x2a"
    assert strip[1] == b"\x00\x00\x00\xef"
    assert strip[2] == b"\x2b"
    assert strip[3] == b"\x00\x00\x00\x3b"
    assert strip[4] == b"\x2c"
    assert spi.lengths[base + 5] == 60 * 480
    assert strip[5][:4] == b"\xf8\x00\xf8\x00"
    assert strip[5][4:6] == b"\x00\x00"


def test_indexed_palette_edit_recolors_drawn_pixels() -> None:
    """A set_color after drawing changes what the next flush sends."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_panel(GC9A01AIndexed, transfer_rows=60)
    panel.set_color(5, 255, 0, 0)
    panel.frame.pixel(0, 60, 5)
    flush = panel.flush()
    next(flush)
    panel.set_color(5, 0, 0, 255)
    base = len(spi.writes)
    next(flush)
    assert spi.writes[base + 5][:2] == b"\x00\x1f"
    assert spi.writes[base + 3] == b"\x00\x3c\x00\x77"


def test_indexed_partial_last_strip() -> None:
    """240 rows in 70-row strips ends with a 30-row strip."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_panel(GC9A01AIndexed, transfer_rows=70)
    base = len(spi.writes)
    flush = panel.flush()
    while True:
        try:
            next(flush)
        except StopIteration:
            break
    data_lengths = [length for length in spi.lengths[base:] if length > 4]
    assert data_lengths == [70 * 480, 70 * 480, 70 * 480, 30 * 480]
    assert spi.writes[base + 21] == b"\x00\xd2\x00\xef"


def test_indexed_frame_completes_under_screen_service() -> None:
    """ScreenService drives one indexed frame to done in four handles."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_panel(GC9A01AIndexed, transfer_rows=60)
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    base = len(spi.writes)
    service.show()
    for tick in range(4):
        assert service.check(tick) is True
        service.handle(tick)
    assert service.check(5) is False
    assert len(spi.writes) - base == 4 * 6


def test_indexed_frame_is_a_framebuf_canvas_that_starts_dirty() -> None:
    """The frame records its bounds and reports the whole panel before the first flush."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_panel(GC9A01AIndexed, transfer_rows=60)
    assert (panel.frame.width, panel.frame.height) == (240, 240)
    assert panel.frame.take_dirty() == (0, 0, 240, 240)
    assert run_flush(panel, spi) == 0


def test_indexed_flush_sends_only_the_strips_the_drawing_touched() -> None:
    """A short vertical line lands as one strip windowed to its column."""
    _skip_unless_indexed_headroom()
    panel, spi = make_drained_indexed_panel()
    panel.frame.vline(100, 120, 11, 7)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 1
    strip = spi.writes[base:]
    assert len(strip) == 6
    assert strip[1] == b"\x00\x64\x00\x64"
    assert strip[3] == b"\x00\x78\x00\xb3"
    assert spi.lengths[base + 5] == 60 * 2
    assert strip[5][:6] == b"\xf8\x00\xf8\x00\xf8\x00"


def test_indexed_flush_with_nothing_drawn_sends_nothing() -> None:
    """A flush after a clean frame ends on its first advance with no bus traffic."""
    _skip_unless_indexed_headroom()
    panel, spi = make_drained_indexed_panel()
    base = len(spi.writes)
    assert run_flush(panel, spi) == 0
    assert len(spi.writes) == base
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    service.show()
    assert service.check(0) is True
    service.handle(0)
    assert service.check(1) is False
    assert len(spi.writes) == base


def test_indexed_narrow_strip_carries_the_dirty_columns_only() -> None:
    """Two pixels three columns apart send a three-pixel-wide strip with the gap between them."""
    _skip_unless_indexed_headroom()
    panel, spi = make_drained_indexed_panel()
    panel.set_color(9, 0, 0, 255)
    run_flush(panel, spi)
    panel.frame.pixel(10, 0, 7)
    panel.frame.pixel(12, 0, 9)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 1
    assert spi.writes[base + 1] == b"\x00\x0a\x00\x0c"
    assert spi.lengths[base + 5] == 60 * 3 * 2
    assert spi.writes[base + 5][:6] == b"\xf8\x00\x00\x00\x00\x1f"


def test_indexed_dirty_rows_across_a_strip_boundary_send_both_strips() -> None:
    """A full-width band over rows 55 to 64 sends strips 0 and 1 at full width."""
    _skip_unless_indexed_headroom()
    panel, spi = make_drained_indexed_panel()
    panel.frame.fill_rect(0, 55, 240, 10, 7)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 2
    assert spi.writes[base + 1] == b"\x00\x00\x00\xef"
    assert spi.writes[base + 3] == b"\x00\x00\x00\x3b"
    assert spi.writes[base + 9] == b"\x00\x3c\x00\x77"
    assert spi.lengths[base + 5] == 60 * 480
    assert spi.lengths[base + 11] == 60 * 480


def test_indexed_narrow_flush_ends_on_a_shorter_last_strip() -> None:
    """With 70-row strips, a line down column 5 from row 210 sends the 30-row last strip one pixel wide."""
    _skip_unless_indexed_headroom()
    panel, spi = make_drained_indexed_panel(transfer_rows=70)
    panel.frame.vline(5, 210, 26, 7)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 1
    assert spi.writes[base + 1] == b"\x00\x05\x00\x05"
    assert spi.writes[base + 3] == b"\x00\xd2\x00\xef"
    assert spi.lengths[base + 5] == 30 * 2
    assert spi.writes[base + 5][:4] == b"\xf8\x00\xf8\x00"


def test_indexed_set_color_marks_the_whole_frame() -> None:
    """Recoloring an index after a flush resends every strip at full width."""
    _skip_unless_indexed_headroom()
    panel, spi = make_drained_indexed_panel()
    panel.set_color(7, 0, 255, 0)
    base = len(spi.writes)
    assert run_flush(panel, spi) == 4
    assert spi.writes[base + 1] == b"\x00\x00\x00\xef"
    assert spi.lengths[base + 5] == 60 * 480
