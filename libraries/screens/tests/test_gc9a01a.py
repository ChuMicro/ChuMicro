"""Host-lane tests for the GC9A01A panel driver.

Runs on CPython and the unix ports through host fakes; silicon is
covered by the functional bench.  The shared framebuf stub seeded
below satisfies the module-load import on runtimes that do not ship
framebuf.
"""

__chumicro_host_only__ = True

import sys

from _framebuf_stub import FramebufStub

sys.modules.setdefault("framebuf", FramebufStub())

from chumicro_screens import ScreenService  # noqa: E402
from chumicro_screens.gc9a01a import GC9A01A, GC9A01AIndexed, color565  # noqa: E402
from chumicro_test_harness import raises, skip  # noqa: E402
from chumicro_timing.testing import FakeTicks  # noqa: E402


def _skip_unless_frame_buffer_headroom() -> None:
    """Loud-skip on heaps that cannot hold the driver's frame buffer."""
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
    """Loud-skip when the indexed frame plus recorded strips overflow."""
    try:
        import gc

        free = gc.mem_free()
    except (ImportError, AttributeError):
        return  # CPython has no gc.mem_free; run the test.
    if free < 400_000:
        skip(
            "GC9A01AIndexed tests hold the 57,600 B frame plus every "
            "strip FakeSpi records; the driver itself fits a 264 KB "
            "board and the bench validates it there",
        )


class FakePin:
    """Records every level the driver drives onto the pin."""

    def __init__(self) -> None:
        self.states: list[int] = []

    def __call__(self, value: int) -> None:
        self.states.append(value)


class FakeSpi:
    """Records every write as an owned bytes copy."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: object) -> None:
        self.writes.append(bytes(data))


class DelayRecorder:
    """Records requested sleeps instead of sleeping."""

    def __init__(self) -> None:
        self.delays: list[int] = []

    def __call__(self, duration_ms: int) -> None:
        self.delays.append(duration_ms)


def make_panel(transfer_rows: int = 10) -> tuple:
    spi = FakeSpi()
    reset = FakePin()
    delays = DelayRecorder()
    panel = GC9A01A(spi, FakePin(), FakePin(), reset,
                    transfer_rows=transfer_rows, sleep_ms=delays)
    return panel, spi, delays, reset


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
    """transfer_rows outside 1..240 is refused."""
    with raises(ValueError):
        make_panel(transfer_rows=0)
    with raises(ValueError):
        make_panel(transfer_rows=241)


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
    assert len(strip[5]) == 60 * 480
    next(flush)
    assert spi.writes[base + 9] == b"\x00\x3c\x00\x77"


def test_flush_advance_count_and_completion() -> None:
    """A 60-row strip frame completes in exactly four advances."""
    _skip_unless_frame_buffer_headroom()
    panel, spi, delays, reset = make_panel(transfer_rows=60)
    base = len(spi.writes)
    flush = panel.flush()
    advances = 0
    while True:
        try:
            next(flush)
        except StopIteration:
            break
        advances += 1
    assert advances == 3
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
    data_lengths = [len(write) for write in spi.writes[base:]
                    if len(write) > 4]
    assert data_lengths == [100 * 480, 100 * 480, 40 * 480]
    assert spi.writes[base + 15] == b"\x00\xc8\x00\xef"


def test_strip_data_comes_from_the_frame_buffer() -> None:
    """Strip N carries the buffer bytes for its rows."""
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


def make_indexed_panel(transfer_rows: int = 10) -> tuple:
    spi = FakeSpi()
    reset = FakePin()
    delays = DelayRecorder()
    panel = GC9A01AIndexed(spi, FakePin(), FakePin(), reset,
                           transfer_rows=transfer_rows, sleep_ms=delays)
    return panel, spi, delays, reset


def test_indexed_construction_resets_then_inits() -> None:
    """Reset and init match the full-color driver; the frame is 8-bit."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_indexed_panel()
    assert reset.states == [1, 0, 1]
    assert delays.delays == [5, 20, 150, 120, 20]
    assert spi.writes[0] == b"\xfe"
    assert spi.writes[-1] == b"\x29"
    assert len(spi.writes) == 34
    assert len(panel._buffer) == 240 * 240
    assert panel.width == 240
    assert panel.height == 240


def test_indexed_transfer_rows_bounds() -> None:
    """transfer_rows outside 1..240 is refused."""
    with raises(ValueError):
        make_indexed_panel(transfer_rows=0)
    with raises(ValueError):
        make_indexed_panel(transfer_rows=241)


def test_indexed_flush_expands_through_the_palette() -> None:
    """Drawn indexes leave the bus as their palette's RGB565 bytes."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_indexed_panel(transfer_rows=60)
    panel.set_color(7, 255, 0, 0)
    panel._buffer[0] = 7
    panel._buffer[1] = 7
    base = len(spi.writes)
    flush = panel.flush()
    next(flush)
    strip = spi.writes[base:]
    assert strip[0] == b"\x2a"
    assert strip[1] == b"\x00\x00\x00\xef"
    assert strip[2] == b"\x2b"
    assert strip[3] == b"\x00\x00\x00\x3b"
    assert strip[4] == b"\x2c"
    assert len(strip[5]) == 60 * 480
    assert strip[5][:4] == b"\xf8\x00\xf8\x00"
    assert strip[5][4:6] == b"\x00\x00"


def test_indexed_palette_edit_recolors_drawn_pixels() -> None:
    """A set_color after drawing changes what the next flush sends."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_indexed_panel(transfer_rows=60)
    panel.set_color(5, 255, 0, 0)
    panel._buffer[60 * 240] = 5
    flush = panel.flush()
    next(flush)
    panel.set_color(5, 0, 0, 255)
    base = len(spi.writes)
    next(flush)
    assert spi.writes[base + 5][:2] == b"\x00\x1f"
    assert spi.writes[base + 3] == b"\x00\x3c\x00\x77"


def test_indexed_partial_last_strip() -> None:
    """240 rows in 100-row strips ends with a 40-row strip."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_indexed_panel(transfer_rows=100)
    base = len(spi.writes)
    flush = panel.flush()
    while True:
        try:
            next(flush)
        except StopIteration:
            break
    data_lengths = [len(write) for write in spi.writes[base:]
                    if len(write) > 4]
    assert data_lengths == [100 * 480, 100 * 480, 40 * 480]
    assert spi.writes[base + 15] == b"\x00\xc8\x00\xef"


def test_indexed_frame_completes_under_screen_service() -> None:
    """ScreenService drives one indexed frame to done in four handles."""
    _skip_unless_indexed_headroom()
    panel, spi, delays, reset = make_indexed_panel(transfer_rows=60)
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    base = len(spi.writes)
    service.show()
    for tick in range(4):
        assert service.check(tick) is True
        service.handle(tick)
    assert service.check(5) is False
    assert len(spi.writes) - base == 4 * 6
