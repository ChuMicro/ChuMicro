"""Host-lane tests for the CircuitPython adapter's scan timing.

``keypad_scan_timing`` is plain arithmetic with no firmware behind it, so the one
knob the library exposes can be checked on a laptop: it turns ``settle_ms`` into the
``interval`` and ``debounce_threshold`` a ``keypad`` scanner is built with.  The
scanners themselves need the firmware module and are covered by ``functional_tests/``
on a real board.

The module is CircuitPython-marked, so a MicroPython deploy never carries it; this
file stays on the host lane where importing it always resolves.
"""

#: Host-lane only: imports a CircuitPython-marked module, which a MicroPython
#: deploy does not carry.  Never staged to a device.
__chumicro_host_only__ = True

from chumicro_buttons._adapters.cp import (
    MINIMUM_SCAN_INTERVAL_SECONDS,
    SCANS_PER_SETTLE_WINDOW,
    keypad_scan_timing,
)


def test_the_default_settle_window_splits_into_four_scans() -> None:
    """A 20 ms window becomes four scans 5 ms apart, which multiply back to 20 ms."""
    interval_seconds, debounce_threshold = keypad_scan_timing(20)

    assert debounce_threshold == SCANS_PER_SETTLE_WINDOW
    assert interval_seconds == 0.005
    assert interval_seconds * debounce_threshold * 1000 == 20


def test_the_window_is_always_the_interval_times_the_threshold() -> None:
    """Across a range of windows, interval times threshold reproduces settle_ms.

    This is the property that makes settle_ms a quiet period rather than a scan
    rate, so it is checked over several windows instead of one.
    """
    for settle_ms in (4, 5, 8, 20, 50, 100, 250):
        interval_seconds, debounce_threshold = keypad_scan_timing(settle_ms)
        window_ms = interval_seconds * debounce_threshold * 1000
        assert abs(window_ms - settle_ms) < 0.001


def test_a_window_of_zero_or_less_scans_as_fast_as_the_runtime_resolves() -> None:
    """settle_ms=0 trusts the signal: the shortest interval and a threshold of one scan."""
    assert keypad_scan_timing(0) == (MINIMUM_SCAN_INTERVAL_SECONDS, 1)
    assert keypad_scan_timing(-5) == (MINIMUM_SCAN_INTERVAL_SECONDS, 1)


def test_a_window_too_short_to_split_counts_the_scans_that_fit() -> None:
    """Below four milliseconds the interval bottoms out and the threshold is the window."""
    assert keypad_scan_timing(1) == (MINIMUM_SCAN_INTERVAL_SECONDS, 1)
    assert keypad_scan_timing(2) == (MINIMUM_SCAN_INTERVAL_SECONDS, 2)
    assert keypad_scan_timing(3) == (MINIMUM_SCAN_INTERVAL_SECONDS, 3)

    # Four milliseconds is the shortest window that still splits four ways.
    assert keypad_scan_timing(4) == (MINIMUM_SCAN_INTERVAL_SECONDS, SCANS_PER_SETTLE_WINDOW)


def test_a_sub_millisecond_window_still_takes_one_scan() -> None:
    """A window under a millisecond keeps a threshold of 1, never 0, so debounce stays on."""
    interval_seconds, debounce_threshold = keypad_scan_timing(0.5)

    assert interval_seconds == MINIMUM_SCAN_INTERVAL_SECONDS
    assert debounce_threshold == 1
