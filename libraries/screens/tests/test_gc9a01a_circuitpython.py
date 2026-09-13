"""CPython-lane tests for the GC9A01A panel on its CircuitPython strip.

Seeds ``displayio``, ``bitmaptools``, and ``terminalio`` with the stubs
in ``_circuitpython_stubs`` and swaps the driver's ``framebuf`` binding
to None, which is what a CircuitPython board looks like to it, so the
panel builds a ``BitmapStrip`` and locks a ``busio``-shaped bus around
each transfer.  Silicon is covered by the functional bench.
"""

__chumicro_runtimes__ = ("cpython",)

import sys

from _circuitpython_stubs import BitmaptoolsStub, DisplayioStub, TerminalioStub

sys.modules.setdefault("displayio", DisplayioStub())
sys.modules.setdefault("bitmaptools", BitmaptoolsStub())
sys.modules.setdefault("terminalio", TerminalioStub())

import pytest  # noqa: E402
from chumicro_screens import gc9a01a  # noqa: E402
from chumicro_screens.bitmap_strip import BitmapStrip  # noqa: E402
from chumicro_screens.gc9a01a import GC9A01A  # noqa: E402


@pytest.fixture(autouse=True)
def _no_framebuf(monkeypatch):
    monkeypatch.setattr(gc9a01a, "framebuf", None)


class FakePin:
    def __init__(self):
        self.states = []

    def __call__(self, value):
        self.states.append(value)


class FakeBusioSpi:
    """A ``busio.SPI`` shape: writes need the lock, and it can refuse the lock a few times."""

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
        view = memoryview(data)
        self.lengths.append(len(view))
        self.writes.append(bytes(view[:8]))


def make_panel(rows=8, refusals=0):
    spi = FakeBusioSpi(refusals=refusals)
    delays = []
    panel = GC9A01A(spi, FakePin(), FakePin(), FakePin(), rows=rows, sleep_ms=delays.append)
    return panel, spi


def test_the_strip_is_a_bitmap_strip_and_bring_up_holds_the_lock():
    panel, spi = make_panel(rows=6)
    assert isinstance(panel.strip, BitmapStrip)
    assert (panel.strip.width, panel.strip.rows) == (240, 6)
    assert spi.lock_count == 1
    assert spi.unlock_count == 1
    assert not spi.locked


def test_write_strip_locks_around_one_transfer_and_streams_the_bitmap():
    panel, spi = make_panel(rows=8)
    panel.strip.top = 8
    panel.strip.fill_rect(0, 8, 2, 1, 0xABCD)
    del spi.writes[:]
    del spi.lengths[:]

    panel.write_strip(8, 8)

    assert spi.lock_count == 2
    assert spi.unlock_count == 2
    assert spi.writes[:5] == [b"\x2a", b"\x00\x00\x00\xef", b"\x2b", b"\x00\x08\x00\x0f", b"\x2c"]
    assert spi.lengths[-1] == 240 * 8 * 2
    assert spi.writes[-1][:4] == b"\xcd\xab\xcd\xab"


def test_a_refused_lock_is_retried_until_it_is_granted():
    panel, spi = make_panel(rows=8, refusals=3)
    assert spi.lock_count == 4
    panel.write_strip(0, 8)
    assert spi.unlock_count == 2
