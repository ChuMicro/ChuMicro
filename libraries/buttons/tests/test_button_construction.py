"""Cross-runtime tests for building a ``Button``: defaults, the clock, and deinit.

Plain asserts plus the harness ``raises()`` helper, so they run on CPython (via pytest) and on
MicroPython/CircuitPython (via the lightweight test harness).  Every edge arrives
from ``FakeButtonSource`` and every duration is measured by ``FakeTicks``, so
nothing here reads a real clock or waits.
"""


from chumicro_buttons import (
    DEFAULT_LONG_PRESS_MS,
    DEFAULT_REPEAT_DELAY_MS,
    DEFAULT_SETTLE_MS,
    Button,
)
from chumicro_buttons.testing import FakeButtonSource
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks


def _quiet_button(source, **options) -> Button:
    """Build a Button on ``source`` with long press, repeat, and clicks off.

    Each test turns back on only the timing it is about, so an unrelated event
    can never be what a tick reports.
    """
    settings = {"long_press_ms": 0, "repeat_ms": 0, "click_ms": 0}
    settings.update(options)
    return Button(source=source, ticks=FakeTicks(), **settings)


# -- Construction, defaults, and lifecycle -----------------------------


def test_the_documented_defaults_are_the_shipped_ones() -> None:
    """The module constants hold the settle, long-press, and repeat-delay defaults."""
    assert DEFAULT_SETTLE_MS == 20
    assert DEFAULT_LONG_PRESS_MS == 500
    assert DEFAULT_REPEAT_DELAY_MS == 500


def test_a_default_button_long_presses_at_the_default_threshold() -> None:
    """Built with no timing arguments, a button long-presses at DEFAULT_LONG_PRESS_MS."""
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks())
    source.press(at_ms=0)
    button.check(0)

    assert button.check(DEFAULT_LONG_PRESS_MS - 1) is False
    assert button.check(DEFAULT_LONG_PRESS_MS) is True
    assert button.just_long_pressed is True
    assert button.just_repeated is False
    assert button.just_clicked is False


def test_a_button_given_no_ticks_falls_back_to_the_library_clock() -> None:
    """Omitting ticks= still measures held_ms from the edge the test stamped."""
    source = FakeButtonSource()
    button = Button(source=source, long_press_ms=0)

    source.press(at_ms=100)
    button.check(160)

    assert button.held_ms == 60


def test_a_button_with_no_pin_and_no_source_tells_you_to_tick_its_panel() -> None:
    """check() on a panel-driven key raises RuntimeError naming the Buttons to tick."""
    button = Button(ticks=FakeTicks())

    with raises(RuntimeError, match="tick the Buttons instead of the key"):
        button.check(0)


def test_deinit_releases_the_source_the_button_owns() -> None:
    """deinit() hands the release straight through to the source."""
    source = FakeButtonSource()
    button = _quiet_button(source)

    button.deinit()

    assert source.deinit_calls == 1


def test_deinit_on_a_panel_driven_button_is_harmless() -> None:
    """A key with no source of its own survives deinit and still refuses check()."""
    button = Button(ticks=FakeTicks())

    button.deinit()

    with raises(RuntimeError, match="tick the Buttons instead of the key"):
        button.check(0)
