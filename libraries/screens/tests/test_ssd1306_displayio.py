"""Host-lane tests for the SSD1306 displayio factory.

Runs on CPython and the unix ports through a busdisplay stand-in;
silicon is covered by the functional bench.  The asserts pin the
factory's passthrough contract, the monochrome parameters displayio
needs told, and the packed shape of the initialization sequence.
"""

__chumicro_host_only__ = True

import sys

from _screen_stubs import BusDisplayStub

sys.modules.setdefault("busdisplay", BusDisplayStub())

from chumicro_screens import ssd1306_displayio  # noqa: E402
from chumicro_screens.ssd1306_displayio import make_display  # noqa: E402
from chumicro_test_harness import raises  # noqa: E402


class FakeDisplayBus:
    """Opaque bus object; the factory must pass it through untouched."""


def test_make_display_builds_the_bus_display() -> None:
    """The factory hands displayio the bus, geometry, and init table."""
    bus = FakeDisplayBus()
    display = make_display(bus)
    assert display.display_bus is bus
    assert display.kwargs["width"] == 128
    assert display.kwargs["height"] == 64
    assert display.kwargs["rotation"] == 0
    assert display.kwargs["auto_refresh"] is True
    assert display.init_sequence == ssd1306_displayio._init_sequence(64)


def test_monochrome_parameters_reach_displayio() -> None:
    """One bit per pixel, stacked down a column, with the panel's own bounds."""
    kwargs = make_display(FakeDisplayBus()).kwargs
    assert kwargs["color_depth"] == 1
    assert kwargs["grayscale"] is True
    assert kwargs["pixels_in_byte_share_row"] is False
    assert kwargs["set_column_command"] == 0x21
    assert kwargs["set_row_command"] == 0x22
    assert kwargs["single_byte_bounds"] is True
    assert kwargs["data_as_commands"] is True
    assert kwargs["brightness_command"] == 0x81


def test_make_display_passes_rotation_and_manual_refresh() -> None:
    """rotation and auto_refresh reach the BusDisplay unchanged."""
    kwargs = make_display(FakeDisplayBus(), rotation=180,
                          auto_refresh=False).kwargs
    assert kwargs["rotation"] == 180
    assert kwargs["auto_refresh"] is False


def test_multiplex_and_com_pins_follow_the_row_count() -> None:
    """A 32-row panel patches its mux ratio and COM pin configuration."""
    tall = ssd1306_displayio._init_sequence(64)
    short = ssd1306_displayio._init_sequence(32)
    assert tall[tall.index(b"\xa8") + 2] == 63
    assert short[short.index(b"\xa8") + 2] == 31
    assert tall[tall.index(b"\xda") + 2] == 0x12
    assert short[short.index(b"\xda") + 2] == 0x02


def test_height_off_the_page_grid_is_refused() -> None:
    """A height that is not whole pages cannot map onto the panel."""
    with raises(ValueError):
        make_display(FakeDisplayBus(), height=60)


def test_init_sequence_parses_as_packed_commands() -> None:
    """The table walks cleanly as (command, count, data) with no delays."""
    sequence = ssd1306_displayio._init_sequence(64)
    commands = []
    index = 0
    while index < len(sequence):
        command_byte = sequence[index]
        control = sequence[index + 1]
        commands.append(command_byte)
        index += 2 + (control & 0x7F)
        assert not control & 0x80          # this panel needs no timed waits
    assert index == len(sequence)
    assert commands[0] == 0xAE             # display off first
    assert commands[-1] == 0xAF            # display on last
    assert 0x8D in commands                # charge pump enabled
    assert len(commands) == 13
