"""Cross-runtime tests for ``Button`` click series: counting taps and closing the window.

Plain asserts, so they run on CPython (via pytest) and on
MicroPython/CircuitPython (via the lightweight test harness).  Every edge arrives
from ``FakeButtonSource`` and every duration is measured by ``FakeTicks``, so
nothing here reads a real clock or waits.
"""


from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


def _quiet_button(source, **options) -> Button:
    """Build a Button on ``source`` with long press, repeat, and clicks off.

    Each test turns back on only the timing it is about, so an unrelated event
    can never be what a tick reports.
    """
    settings = {"long_press_ms": 0, "repeat_ms": 0, "click_ms": 0}
    settings.update(options)
    return Button(source=source, ticks=FakeTicks(), **settings)


# -- Click counting ----------------------------------------------------


def test_one_press_and_release_resolves_to_a_click_count_of_one() -> None:
    """A single tap publishes click_count 1 once the quiet window closes."""
    source = FakeButtonSource()
    button = _quiet_button(source, click_ms=100)
    source.press(at_ms=0)
    button.check(0)
    source.release(at_ms=20)
    button.check(20)

    assert button.check(119) is False
    assert button.just_clicked is False

    assert button.check(120) is True
    assert button.just_clicked is True
    assert button.click_count == 1


def test_two_taps_inside_the_window_resolve_to_one_click_of_two() -> None:
    """Two press/release pairs inside click_ms publish click_count 2 on one tick."""
    source = FakeButtonSource()
    button = _quiet_button(source, click_ms=250)

    source.press(at_ms=0)
    button.check(0)
    source.release(at_ms=40)
    button.check(40)
    source.press(at_ms=100)
    button.check(100)
    source.release(at_ms=140)
    button.check(140)

    clicked_at = []
    for tick_ms in range(150, 501, 10):
        button.check(tick_ms)
        if button.just_clicked:
            clicked_at.append(tick_ms)

    assert clicked_at == [390]
    assert button.click_count == 2


def test_a_new_press_before_the_window_closes_cancels_the_pending_resolve() -> None:
    """Pressing again inside click_ms holds the series open past the first deadline."""
    source = FakeButtonSource()
    button = _quiet_button(source, click_ms=200)
    source.press(at_ms=0)
    button.check(0)
    source.release(at_ms=50)
    button.check(50)

    source.press(at_ms=150)
    button.check(150)

    assert button.check(250) is False
    assert button.just_clicked is False
    assert button.click_count == 0


def test_a_press_held_past_the_window_is_a_hold_and_never_joins_the_count() -> None:
    """A hold closes the tap's series while it is still down and never counts itself.

    The tap resolves to click_count 1 on the tick the hold outlives click_ms, and the
    release a minute later adds nothing, so a tap followed by a long press is not a
    double click.
    """
    source = FakeButtonSource()
    button = _quiet_button(source, long_press_ms=500, click_ms=300)

    source.press(at_ms=0)
    button.check(0)
    source.release(at_ms=50)
    button.check(50)

    source.press(at_ms=100)
    button.check(100)
    assert button.just_clicked is False

    assert button.check(400) is True
    assert button.just_clicked is True
    assert button.click_count == 1

    source.release(at_ms=60000)
    button.check(60000)
    assert button.just_clicked is False
    assert button.held_ms == 59900

    assert button.check(60300) is False
    assert button.just_clicked is False
    assert button.click_count == 1


def test_click_ms_zero_disables_click_counting() -> None:
    """With click_ms=0 a tap leaves click_count at 0 and never fires just_clicked."""
    source = FakeButtonSource()
    button = _quiet_button(source, click_ms=0)
    source.press(at_ms=0)
    button.check(0)
    source.release(at_ms=50)
    button.check(50)

    for tick_ms in (100, 500, 5000):
        assert button.check(tick_ms) is False
        assert button.just_clicked is False

    assert button.click_count == 0
