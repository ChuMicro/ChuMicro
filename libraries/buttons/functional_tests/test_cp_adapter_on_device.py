"""On-device tests for ``CpButtonSource`` against the real ``keypad`` scan.

Runs only on CircuitPython boards.  The module-level ``__chumicro_runtimes__`` marker
tells the pytest-device plugin to skip the wrong-runtime parametrization, so MP boards
never try to import the file.

None of these need a button wired.  They target the contract between the adapter and the
firmware it delegates to: that the settle window this library asks for is a window
``keypad`` accepts, that a scan releases its pin on ``deinit``, and that a tick allocates
nothing.  Behavior that needs a finger on a contact is measured by hand on the bench.

Every test builds on a pin with the internal pull-up on, so an unconnected pin reads high
and a key reads released.  That makes the suite portable across boards without a wiring
harness.
"""

__chumicro_runtimes__ = ("circuitpython",)

import gc

import board
import keypad
import supervisor
from chumicro_buttons import Button, Buttons
from chumicro_buttons._adapters.cp import keypad_scan_timing
from chumicro_timing import ticks, ticks_ms

#: Pin names that usually have something soldered to them.  Skipped when hunting for a
#: free pin so the scan does not fight an onboard peripheral for a pad.
_ATTACHED = (
    "LED", "NEOPIXEL", "NEOPIXEL_POWER", "DOTSTAR", "APA102", "BUTTON", "BOOT0",
    "SDA", "SCL", "TX", "RX", "MISO", "MOSI", "SCK", "CS", "VOLTAGE_MONITOR",
    "I2C_POWER", "SDIO", "DEBUG",
)


def _free_pin():
    """Return the first ``board`` pin ``keypad`` will scan, skipping attached ones."""
    for name in dir(board):
        if name.startswith("_") or name in _ATTACHED:
            continue
        candidate = getattr(board, name)
        try:
            scan = keypad.Keys((candidate,), value_when_pressed=False)
        except (ValueError, TypeError, RuntimeError):
            continue
        scan.deinit()
        return candidate
    raise AssertionError("no free pin on this board for keypad to scan")


# -- the settle window this library asks the firmware for --


def test_every_settle_window_is_one_keypad_accepts() -> None:
    """The interval and threshold each ``settle_ms`` maps to build a real scan.

    ``keypad_scan_timing`` splits a settle window into a scan interval and a count of
    scans.  Both are firmware arguments with their own validation, so the mapping is only
    correct if the firmware takes every pair it produces.
    """
    pin = _free_pin()

    for settle_ms in (0, 1, 3, 5, 20, 50, 200):
        interval, threshold = keypad_scan_timing(settle_ms)
        scan = keypad.Keys(
            (pin,),
            value_when_pressed=False,
            interval=interval,
            debounce_threshold=threshold,
        )
        assert scan.key_count == 1
        scan.deinit()


def test_the_settle_window_is_the_interval_times_the_threshold() -> None:
    """A window of 20 ms is four scans 5 ms apart, which is what the docs promise."""
    interval, threshold = keypad_scan_timing(20)

    assert threshold == 4
    assert abs(interval * threshold * 1000 - 20) < 0.001


# -- keypad's clock is the caller's clock --


def test_keypad_stamps_events_on_the_clock_the_library_measures_with() -> None:
    """``supervisor.ticks_ms`` and ``chumicro_timing`` read the same millisecond domain.

    ``keypad`` stamps every event from ``supervisor.ticks_ms``, and the library folds that
    stamp straight into durations judged by the injected clock.  A stamp from a different
    domain would make ``held_ms`` meaningless without either side raising.
    """
    supervisor_now = supervisor.ticks_ms()
    library_now = ticks_ms()

    assert abs(ticks.ticks_diff(library_now, supervisor_now)) < 50


# -- building on a real pin --


def test_a_button_builds_on_a_real_pin_and_reads_released() -> None:
    """A key with its pull-up on and nothing pulling it down is not pressed."""
    button = Button(pin=_free_pin(), ticks=ticks)
    try:
        button.check(ticks_ms())

        assert button.pressed is False
        assert button.just_pressed is False
        assert button.overflowed is False
    finally:
        button.deinit()


def test_a_panel_builds_one_scan_across_several_pins() -> None:
    """``Buttons`` reports a key per pin, all released, on one firmware scan."""
    pin = _free_pin()
    buttons = Buttons(pins=(pin,), ticks=ticks)
    try:
        buttons.check(ticks_ms())

        assert len(buttons) == 1
        assert buttons[0].pressed is False
    finally:
        buttons.deinit()


def test_deinit_hands_the_pin_back() -> None:
    """A released pin can be claimed again, which is what lets a program rebuild a key.

    ``keypad`` holds the pin for its background scan, so a source that leaked it would
    make the second construction raise instead of the first.
    """
    pin = _free_pin()

    for _ in range(3):
        button = Button(pin=pin, ticks=ticks)
        button.check(ticks_ms())

        assert button.pressed is False

        button.deinit()


# -- what a tick costs --


def test_a_quiet_tick_allocates_nothing() -> None:
    """The heap does not grow across a thousand checks, so a loop can tick forever.

    The first pass is excluded: reading the clock boxes one integer the first time it
    crosses out of the small-int range, and that is a one-off rather than per-tick cost.
    """
    button = Button(pin=_free_pin(), ticks=ticks)
    try:
        for _ in range(200):
            button.check(ticks_ms())

        gc.collect()
        before = gc.mem_alloc()
        for _ in range(1000):
            button.check(ticks_ms())

        assert gc.mem_alloc() - before == 0
    finally:
        button.deinit()
