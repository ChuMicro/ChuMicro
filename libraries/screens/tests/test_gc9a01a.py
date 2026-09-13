"""Host-lane tests for the GC9A01A panel on its MicroPython strip.

Runs on CPython and the unix ports through host fakes; silicon is
covered by the functional bench.  The shared framebuf stub seeded
below satisfies the module-load import on runtimes that do not ship
framebuf, so the panel builds a ``FramebufStrip``.  The asserts read
the bytes and pin levels the bring-up and one strip write put on the
bus.
"""

__chumicro_host_only__ = True

import sys

from _screen_stubs import FramebufStub

sys.modules.setdefault("framebuf", FramebufStub())

from chumicro_screens.gc9a01a import GC9A01A, color565  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402


class FakePin:
    """Records every level the driver drives onto the pin."""

    def __init__(self) -> None:
        self.states: list[int] = []

    def __call__(self, value: int) -> None:
        self.states.append(value)


class FakeSpi:
    """Records each write's length and its first eight bytes."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.lengths: list[int] = []

    def write(self, data: object) -> None:
        self.lengths.append(len(data))
        self.writes.append(bytes(data[:8]))


def make_panel(rows: int = 8) -> tuple:
    spi = FakeSpi()
    reset = FakePin()
    chip_select = FakePin()
    data_command = FakePin()
    delays: list[int] = []
    panel = GC9A01A(spi, chip_select, data_command, reset, rows=rows, sleep_ms=delays.append)
    return panel, spi, chip_select, data_command, reset, delays


def test_color565_packs_and_swaps_into_wire_order() -> None:
    assert color565(255, 0, 0) == 0x00F8
    assert color565(0, 255, 0) == 0xE007
    assert color565(0, 0, 255) == 0x1F00
    assert color565(255, 255, 255) == 0xFFFF


def test_bring_up_pulses_reset_then_walks_the_init_sequence_with_its_delays() -> None:
    _, spi, chip_select, data_command, reset, delays = make_panel()

    assert reset.states == [1, 0, 1]
    assert delays == [5, 20, 150, 120, 20]
    assert spi.writes[0] == b"\xfe"
    assert spi.writes[-2:] == [b"\x11", b"\x29"]
    assert chip_select.states[0] == 0 and chip_select.states[-1] == 1
    assert data_command.states[0] == 0


def test_the_strip_is_rows_of_rgb565_at_the_panel_width() -> None:
    panel, _, _, _, _, _ = make_panel(rows=6)
    assert (panel.width, panel.height) == (240, 240)
    assert (panel.strip.width, panel.strip.rows) == (240, 6)
    assert len(panel.strip.buffer) == 240 * 6 * 2


def test_rows_must_divide_the_panel_height() -> None:
    with raises(ValueError):
        make_panel(rows=7)
    with raises(ValueError):
        make_panel(rows=0)
    make_panel(rows=24)


def test_write_strip_sends_the_window_then_the_strip_as_one_transfer() -> None:
    panel, spi, chip_select, data_command, _, _ = make_panel(rows=8)
    del spi.writes[:]
    del spi.lengths[:]
    del chip_select.states[:]
    del data_command.states[:]

    panel.write_strip(16, 8, 0, 240)

    assert spi.writes == [b"\x2a", b"\x00\x00\x00\xef", b"\x2b", b"\x00\x10\x00\x17", b"\x2c",
                          bytes(8)]
    assert spi.lengths[-1] == 240 * 8 * 2
    assert chip_select.states == [0, 1]
    assert data_command.states == [0, 1, 0, 1, 0, 1]


def test_write_strip_sends_what_the_strip_holds() -> None:
    panel, spi, _, _, _, _ = make_panel(rows=8)
    panel.strip.top = 8
    panel.strip.fill_rect(0, 8, 2, 1, 0xABCD)
    del spi.writes[:]

    panel.write_strip(8, 8, 0, 240)

    assert spi.writes[-1][:4] == b"\xcd\xab\xcd\xab"


def test_a_column_window_narrows_the_strip_and_the_transfer() -> None:
    """A 60-column window lays the strip out at 60 wide and sends 60 pixels a row after its column bytes."""
    panel, spi, _, _, _, _ = make_panel(rows=8)
    strip = panel.strip
    strip.window(40, 100)
    strip.top = 8
    strip.clear(0)
    strip.fill_rect(40, 8, 1, 1, 0xABCD)
    strip.fill_rect(100, 8, 1, 1, 0x1234)        # past the window: clipped
    del spi.writes[:]
    del spi.lengths[:]

    panel.write_strip(8, 8, 40, 100)

    assert spi.writes[1] == b"\x00\x28\x00\x63"
    assert spi.lengths[-1] == 60 * 8 * 2
    assert spi.writes[-1][:4] == b"\xcd\xab\x00\x00"
    strip.window(0, 240)
    assert strip.left == 0
    assert strip.window_width == 240
