"""Cross-runtime tests for ScreenService flush pacing.

Plain asserts plus the harness ``raises()`` helper, so they run on
CPython via pytest and on the MicroPython / CircuitPython unix ports
through the test harness.
"""

from chumicro_screens import ScreenService
from chumicro_screens.testing import FakePanel
from chumicro_test_harness import raises
from chumicro_timing import ticks_ms
from chumicro_timing.testing import FakeTicks


class UnwrappedTicks:
    """Clock with plain subtraction and no wrap, to catch a hardcoded tick import."""

    def __init__(self, start_ms: int) -> None:
        self.current_ms = start_ms

    def ticks_ms(self) -> int:
        return self.current_ms

    def ticks_add(self, ticks_value: int, delta: int) -> int:
        return ticks_value + delta

    def ticks_diff(self, end: int, start: int) -> int:
        return end - start


def test_clean_service_is_idle() -> None:
    """Without show(), check() is False and next_deadline() is None."""
    service = ScreenService(FakePanel(), ticks=FakeTicks())
    assert service.check(0) is False
    assert service.next_deadline(0) is None


def test_first_show_flushes_immediately() -> None:
    """The first frame is due at construction time and one transfer completes it."""
    panel = FakePanel(transfers_per_flush=1)
    service = ScreenService(panel, ticks=FakeTicks())
    service.show()
    assert service.check(0) is True
    service.handle(0)
    assert panel.flushes_started == 1
    assert panel.flushes_completed == 1
    assert panel.transfers_completed == 1
    assert service.check(0) is False


def test_multi_transfer_flush_takes_one_tick_per_transfer() -> None:
    """A 3-transfer frame stays active across 3 handle() calls and then goes idle."""
    panel = FakePanel(transfers_per_flush=3)
    service = ScreenService(panel, ticks=FakeTicks())
    service.show()
    service.handle(0)
    assert panel.transfers_completed == 1
    assert panel.flushes_completed == 0
    assert service.check(0) is True
    service.handle(1)
    assert panel.transfers_completed == 2
    assert service.check(1) is True
    service.handle(2)
    assert panel.transfers_completed == 3
    assert panel.flushes_completed == 1
    assert service.check(2) is False


def test_interval_floor_delays_the_next_frame() -> None:
    """A second show() waits out refresh_interval_ms from the prior flush start."""
    panel = FakePanel()
    service = ScreenService(panel, refresh_interval_ms=50, ticks=FakeTicks())
    service.show()
    service.handle(0)
    service.show()
    assert service.check(49) is False
    assert service.next_deadline(49) == 50
    assert service.check(50) is True
    service.handle(50)
    assert panel.flushes_completed == 2


def test_zero_interval_reflushes_back_to_back() -> None:
    """refresh_interval_ms=0 lets every show() flush on the next tick."""
    panel = FakePanel()
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    service.show()
    service.handle(0)
    service.show()
    assert service.check(0) is True
    service.handle(0)
    assert panel.flushes_completed == 2


def test_show_during_active_flush_marks_the_next_frame() -> None:
    """show() mid-flush finishes the current frame, then schedules a fresh one."""
    panel = FakePanel(transfers_per_flush=2)
    service = ScreenService(panel, refresh_interval_ms=10, ticks=FakeTicks())
    service.show()
    service.handle(0)
    service.show()
    service.handle(1)
    assert panel.flushes_started == 1
    assert panel.flushes_completed == 1
    assert service.check(9) is False
    assert service.check(10) is True
    service.handle(10)
    assert panel.flushes_started == 2


def test_panel_fault_drops_the_frame_and_propagates() -> None:
    """A bus fault raises out of handle(), the frame is dropped, and a later show() flushes fresh."""
    panel = FakePanel(transfers_per_flush=3)
    panel.fail_on_transfer = 1
    service = ScreenService(panel, refresh_interval_ms=0, ticks=FakeTicks())
    service.show()
    service.handle(0)
    with raises(OSError):
        service.handle(1)
    assert service.check(2) is False
    assert service.next_deadline(2) is None
    panel.fail_on_transfer = None
    service.show()
    service.handle(2)
    service.handle(3)
    service.handle(4)
    assert panel.flushes_completed == 1


def test_next_deadline_tracks_service_state() -> None:
    """next_deadline() is now during a flush, the floor when waiting, None when idle."""
    panel = FakePanel(transfers_per_flush=2)
    service = ScreenService(panel, refresh_interval_ms=20, ticks=FakeTicks())
    service.show()
    assert service.next_deadline(0) == 0
    service.handle(0)
    assert service.next_deadline(5) == 5
    service.handle(5)
    assert service.next_deadline(6) is None


def test_deadlines_use_the_injected_clock() -> None:
    """A no-wrap plain-subtraction clock is honored, so no helper hardcodes chumicro ticks."""
    clock = UnwrappedTicks(600_000_000)
    panel = FakePanel()
    service = ScreenService(panel, refresh_interval_ms=1_000, ticks=clock)
    service.show()
    assert service.check(600_000_000) is True
    service.handle(600_000_000)
    service.show()
    assert service.check(600_000_999) is False
    assert service.next_deadline(600_000_999) == 600_001_000
    assert service.check(600_001_000) is True


def test_default_clock_construction_flushes() -> None:
    """Without ticks=, the service runs on the real chumicro_timing clock."""
    panel = FakePanel()
    service = ScreenService(panel)
    service.show()
    now_ms = ticks_ms()
    assert service.check(now_ms) is True
    service.handle(now_ms)
    assert panel.flushes_completed == 1


def test_zero_transfer_panel_completes_in_one_tick() -> None:
    """A panel with nothing to send finishes its flush on the first handle()."""
    panel = FakePanel(transfers_per_flush=0)
    service = ScreenService(panel, ticks=FakeTicks())
    service.show()
    service.handle(0)
    assert panel.flushes_started == 1
    assert panel.flushes_completed == 1
    assert panel.transfers_completed == 0
    assert service.check(0) is False
