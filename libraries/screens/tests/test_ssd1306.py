"""Host-lane tests for the SSD1306 panel driver.

Runs on CPython and the unix ports through host fakes; silicon is
covered by the functional bench.  The shared framebuf stub seeded
below satisfies the module-load import on runtimes that do not ship
framebuf, and its MONO_VLSB addressing lets a test draw a pixel into
the page strip and assert on the byte the driver puts on the bus.
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
    delays = []
    panel = SSD1306(i2c, sleep_ms=delays.append, **kwargs)
    init_writes = list(i2c.writes)
    del i2c.writes[:]
    return panel, i2c, init_writes, delays


def test_init_turns_the_display_on_and_enables_the_charge_pump():
    _, _, init_writes, delays = build_panel()

    assert len(init_writes) == 1
    address, payload = init_writes[0]
    assert address == 0x3C
    assert payload[0] == 0x00                    # command-stream control byte
    assert payload[1] == 0xAE                    # display off while configuring
    assert payload[-3:] == bytes((0x8D, 0x14, 0xAF))
    assert delays == [100]


def test_init_forces_the_scroll_and_test_pattern_state_back():
    """Start line, offset, and resume-from-RAM restate the power-on defaults."""
    _, _, init_writes, _ = build_panel()

    payload = init_writes[0][1]
    assert b"\x40" in payload                    # start line 0
    assert b"\xd3\x00" in payload                # display offset 0
    assert 0xA4 in payload                       # show RAM, not all-on


def test_multiplex_and_com_pins_follow_the_row_count():
    _, _, tall, _ = build_panel(height=64)
    _, _, short, _ = build_panel(height=32)

    tall_payload = tall[0][1]
    short_payload = short[0][1]
    assert tall_payload[tall_payload.index(b"\xa8") + 1] == 63
    assert short_payload[short_payload.index(b"\xa8") + 1] == 31
    assert tall_payload[tall_payload.index(b"\xda") + 1] == 0x12
    assert short_payload[short_payload.index(b"\xda") + 1] == 0x02


def test_height_must_be_whole_pages():
    with raises(ValueError):
        build_panel(height=60)


def test_the_strip_is_one_page_in_mono_vlsb():
    panel, _, _, _ = build_panel()
    assert (panel.width, panel.height) == (128, 64)
    assert (panel.strip.width, panel.strip.rows) == (128, 8)
    assert panel.strip.framebuffer.pixel_format == sys.modules["framebuf"].MONO_VLSB


def test_write_strip_addresses_the_page_and_sends_it_behind_the_data_control_byte():
    panel, i2c, _, _ = build_panel()
    strip = panel.strip
    strip.top = 8
    strip.clear(0)
    strip.fill_rect(3, 13, 1, 1, 1)              # panel row 13 is row 5 of page 1

    panel.write_strip(8, 8)

    assert i2c.writes[0] == (0x3C, bytes((0x00, 0x21, 0, 127, 0x22, 1, 1)))
    address, payload = i2c.writes[1]
    assert address == 0x3C
    assert len(payload) == 129
    assert payload[0] == 0x40
    assert payload[1 + 3] == 1 << 5
    assert sum(payload[1:]) == 1 << 5


def test_the_last_page_of_a_short_panel_is_addressable():
    panel, i2c, _, _ = build_panel(height=32)
    panel.write_strip(24, 8)
    assert i2c.writes[0][1][-2:] == bytes((3, 3))


def test_set_contrast_sends_the_command_and_the_level_as_two_writes():
    panel, i2c, _, _ = build_panel()
    panel.set_contrast(0x7F)
    assert i2c.writes == [(0x3C, bytes((0x00, 0x81))), (0x3C, bytes((0x00, 0x7F)))]
    with raises(ValueError):
        panel.set_contrast(256)
