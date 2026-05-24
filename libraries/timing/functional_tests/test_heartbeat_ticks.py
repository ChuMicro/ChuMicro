"""Device-facing tests for the cross-runtime timing helpers."""

from chumicro_timing.testing import sleep_ms
from chumicro_timing.ticks import ticks_diff, ticks_ms


def test_ticks_progress_on_runtime() -> None:
    """The active runtime should expose forward-moving monotonic ticks."""
    start_ms = ticks_ms()
    sleep_ms(20)
    end_ms = ticks_ms()

    assert ticks_diff(end_ms, start_ms) >= 1
