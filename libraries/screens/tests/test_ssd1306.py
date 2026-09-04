"""Host-lane tests for the SSD1306 panel driver.

Runs on CPython and the unix ports through host fakes; silicon is
covered by the functional bench.  The shared framebuf stub seeded
below satisfies the module-load import on runtimes that do not ship
framebuf, and its MONO_VLSB addressing lets a test draw a pixel and
assert on the byte the driver puts on the bus.
"""

__chumicro_host_only__ = True

import sys

from _screen_stubs import FramebufStub

sys.modules.setdefault("framebuf", FramebufStub())

from chumicro_screens.ssd1306 import SSD1306  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402


class FakeI2C:
    """Records every transaction the driver puts on the bus."""

    def __init__(self) -> None:
        self.writes = []

    def writeto(self, address, buffer) -> None:
        self.writes.append((address, bytes(buffer)))


def build_panel(**kwargs) -> tuple:
    """Construct a panel on a fake bus and drop the init traffic."""
    i2c = FakeI2C()
    panel = SSD1306(i2c, sleep_ms=[].append, **kwargs)
    init_writes = list(i2c.writes)
    del i2c.writes[:]
    return panel, i2c, init_writes


def drain(panel) -> int:
    """Run one whole flush and return how many advances it took."""
    advances = 1
    flush = panel.flush()
    for _ in flush:
        advances += 1
    return advances


def test_init_turns_the_display_on_and_enables_the_charge_pump():
    _, _, init_writes = build_panel()

    assert len(init_writes) == 1
    address, payload = init_writes[0]
    assert address == 0x3C
    assert payload[0] == 0x00                    # command-stream control byte
    assert payload[1] == 0xAE                    # display off while configuring
    assert payload[-3:] == bytes((0x8D, 0x14, 0xAF))


def test_init_forces_the_scroll_and_test_pattern_state_back():
    """Start line, offset, and resume-from-RAM restate the power-on defaults."""
    _, _, init_writes = build_panel()

    payload = init_writes[0][1]
    assert b"\x40" in payload                    # start line 0
    assert b"\xd3\x00" in payload                # display offset 0
    assert 0xA4 in payload                       # show RAM, not all-on


def test_multiplex_and_com_pins_follow_the_row_count():
    _, _, tall = build_panel(height=64)
    _, _, short = build_panel(height=32)

    tall_payload = tall[0][1]
    short_payload = short[0][1]
    assert tall_payload[tall_payload.index(b"\xa8") + 1] == 63
    assert short_payload[short_payload.index(b"\xa8") + 1] == 31
    assert tall_payload[tall_payload.index(b"\xda") + 1] == 0x12
    assert short_payload[short_payload.index(b"\xda") + 1] == 0x02


def test_height_off_the_page_grid_is_refused():
    with raises(ValueError, match="multiple of 8"):
        SSD1306(FakeI2C(), height=60, sleep_ms=[].append)


def test_transfer_pages_outside_the_page_count_is_refused():
    with raises(ValueError, match="1 to 8"):
        SSD1306(FakeI2C(), transfer_pages=9, sleep_ms=[].append)


def test_a_full_frame_takes_one_advance_per_page():
    panel, _, _ = build_panel()

    assert drain(panel) == 8


def test_transfer_pages_groups_pages_into_fewer_advances():
    panel, i2c, _ = build_panel(transfer_pages=4)

    assert drain(panel) == 2
    assert len(i2c.writes) == 10                 # two windows, eight page writes
    for _, payload in i2c.writes[1:5]:
        assert payload[0] == 0x40
        assert len(payload) == 129


def test_a_trailing_group_carries_only_the_pages_that_remain():
    panel, i2c, _ = build_panel(transfer_pages=3)

    advances = drain(panel)

    assert advances == 3
    last_commands = i2c.writes[-3][1]            # window ahead of pages 6 and 7
    assert last_commands[-2:] == bytes((6, 7))   # page span of the short group


def test_each_advance_windows_its_pages_then_sends_their_bytes():
    panel, i2c, _ = build_panel()

    drain(panel)

    assert len(i2c.writes) == 16                 # a window and a payload per page
    commands, payload = i2c.writes[0][1], i2c.writes[1][1]
    assert commands == bytes((0x00, 0x21, 0, 127, 0x22, 0, 0))
    assert payload[0] == 0x40                    # data-stream control byte
    assert len(payload) == 129


def test_a_drawn_pixel_reaches_the_bus_in_its_own_page():
    panel, i2c, _ = build_panel()
    panel.frame.pixel(5, 9, 1)                   # row 9 is page 1, bit 1

    drain(panel)

    page_one_payload = i2c.writes[3][1]
    assert page_one_payload[1 + 5] == 0b10
    assert set(i2c.writes[1][1][1:]) == {0}      # page 0 stays dark


def test_drawing_at_page_edges_never_touches_a_control_byte():
    """framebuf's stride steps over the prefix ahead of every page row."""
    panel, i2c, _ = build_panel()
    panel.frame.pixel(127, 7, 1)                 # page 0, last column, top bit
    panel.frame.pixel(0, 8, 1)                   # page 1, first column, low bit

    drain(panel)

    assert i2c.writes[1][1][1 + 127] == 0b1000_0000
    assert i2c.writes[3][1][0] == 0x40
    assert i2c.writes[3][1][1] == 0b1


def test_drawing_mid_flush_lands_only_in_pages_still_to_send():
    """A page already on the bus is never resent; a later page carries the new pixel."""
    panel, i2c, _ = build_panel()
    flush = panel.flush()
    next(flush)                                  # page 0 crossed the bus
    panel.frame.pixel(0, 0, 1)                   # page 0, already sent
    panel.frame.pixel(3, 63, 1)                  # page 7, bit 7, still to send

    for _ in flush:
        pass

    assert len(i2c.writes) == 16
    assert i2c.writes[1][1][1] == 0              # page 0 as it went out
    assert i2c.writes[15][1][1 + 3] == 0b1000_0000


def test_set_contrast_sends_the_level_and_refuses_an_out_of_range_one():
    panel, i2c, _ = build_panel()

    panel.set_contrast(0x40)

    assert [payload for _, payload in i2c.writes] == [
        bytes((0x00, 0x81)), bytes((0x00, 0x40))]
    with raises(ValueError, match="0..255"):
        panel.set_contrast(256)
