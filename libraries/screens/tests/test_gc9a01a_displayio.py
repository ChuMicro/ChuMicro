"""Host-lane tests for the GC9A01A displayio factory.

Runs on CPython and the unix ports through a busdisplay stand-in;
silicon is covered by the functional bench.  The asserts pin the
factory's passthrough contract and the packed shape of the
initialization sequence displayio consumes.
"""

__chumicro_host_only__ = True

import sys

from _screen_stubs import BusDisplayStub

sys.modules.setdefault("busdisplay", BusDisplayStub())

from chumicro_screens import gc9a01a, gc9a01a_displayio  # noqa: E402
from chumicro_screens.gc9a01a_displayio import make_display  # noqa: E402


class FakeFourWire:
    """Opaque bus object; the factory must pass it through untouched."""


def test_init_table_matches_the_micropython_driver() -> None:
    """Both runtimes bring the panel up with one table, so neither can drift."""
    assert gc9a01a_displayio._INIT_SEQUENCE == gc9a01a._INIT_SEQUENCE


def test_make_display_builds_the_bus_display() -> None:
    """The factory hands displayio the bus, geometry, and init table."""
    bus = FakeFourWire()
    display = make_display(bus)
    assert display.display_bus is bus
    assert display.width == 240
    assert display.height == 240
    assert display.rotation == 0
    assert display.auto_refresh is True
    assert display.init_sequence == gc9a01a_displayio._INIT_SEQUENCE


def test_make_display_passes_rotation_and_manual_refresh() -> None:
    """rotation and auto_refresh reach the BusDisplay unchanged."""
    display = make_display(FakeFourWire(), rotation=180, auto_refresh=False)
    assert display.rotation == 180
    assert display.auto_refresh is False


def test_init_sequence_parses_as_packed_commands() -> None:
    """The table walks cleanly as (command, count | delay-flag, data)."""
    sequence = gc9a01a_displayio._INIT_SEQUENCE
    commands = []
    delays = []
    index = 0
    while index < len(sequence):
        command_byte = sequence[index]
        control = sequence[index + 1]
        count = control & 0x7F
        commands.append(command_byte)
        if command_byte == 0x3A:
            assert sequence[index + 2:index + 3] == b"\x05"
        index += 2 + count
        if control & 0x80:
            delays.append((command_byte, sequence[index]))
            index += 1
    assert index == len(sequence)
    assert commands[0] == 0xFE
    assert commands[-1] == 0x29
    assert len(commands) == 20
    assert delays == [(0x11, 120), (0x29, 20)]
