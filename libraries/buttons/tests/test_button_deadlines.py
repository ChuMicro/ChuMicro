"""Cross-runtime tests for ``next_deadline``: what a runner's sleep must wake for.

Plain asserts, so they run on CPython (via pytest) and on
MicroPython/CircuitPython (via the lightweight test harness).  Every edge arrives
from ``FakeButtonSource`` and every duration is measured by ``FakeTicks``, so
nothing here reads a real clock or waits.
"""

from chumicro_buttons import Button, Buttons
from chumicro_buttons.testing import FakeButtonSource
from chumicro_runner import Runner
from chumicro_timing.testing import FakeTicks


def test_an_idle_button_publishes_no_deadline() -> None:
    """With no press seen and no click pending, next_deadline returns None."""
    button = Button(source=FakeButtonSource(), ticks=FakeTicks())
    button.check(0)

    assert button.next_deadline(0) is None


def test_a_held_key_publishes_the_long_press_deadline() -> None:
    """While held, next_deadline is the press edge plus long_press_ms."""
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=500)
    source.press(at_ms=100)
    button.check(120)

    assert button.next_deadline(120) == 600


def test_the_long_press_deadline_clears_once_it_fires() -> None:
    """After just_long_pressed, the hold arms no further long-press deadline."""
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=500)
    source.press(at_ms=100)
    button.check(700)

    assert button.just_long_pressed is True
    assert button.next_deadline(700) is None


def test_the_earliest_of_repeat_and_long_press_wins() -> None:
    """With both armed, next_deadline is the sooner of the two timers."""
    source = FakeButtonSource()
    button = Button(
        source=source, ticks=FakeTicks(),
        long_press_ms=500, repeat_ms=100, repeat_delay_ms=200,
    )
    source.press(at_ms=0)
    button.check(0)

    assert button.next_deadline(0) == 200


def test_a_closing_click_series_publishes_its_window_deadline() -> None:
    """After a tap, next_deadline is the release edge plus click_ms."""
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=0, click_ms=250)
    source.press(at_ms=0)
    button.check(0)
    source.release(at_ms=40)
    button.check(40)

    assert button.next_deadline(40) == 290


def test_a_hold_with_click_counting_publishes_the_series_close() -> None:
    """A press still inside the click window arms the hold-closes-series deadline."""
    source = FakeButtonSource()
    button = Button(source=source, ticks=FakeTicks(), long_press_ms=0, click_ms=250)
    source.press(at_ms=100)
    button.check(110)

    assert button.next_deadline(110) == 350


def test_a_panel_publishes_the_earliest_deadline_across_its_keys() -> None:
    """Buttons.next_deadline is the soonest of every key's timers."""
    source = FakeButtonSource(key_count=2)
    buttons = Buttons(source=source, ticks=FakeTicks(), long_press_ms=500)
    source.press(key_index=0, at_ms=300)
    source.press(key_index=1, at_ms=100)
    buttons.check(310)

    assert buttons.next_deadline(310) == 600


def test_a_panel_with_no_timers_armed_publishes_none() -> None:
    """A panel of released keys leaves the runner free to sleep."""
    buttons = Buttons(source=FakeButtonSource(key_count=2), ticks=FakeTicks())
    buttons.check(0)

    assert buttons.next_deadline(0) is None


def test_the_runner_sleeps_exactly_to_a_registered_buttons_long_press() -> None:
    """Runner.wait advances a fake clock to the long-press deadline and the next
    tick fires the event, and a runner that stopped reading next_deadline would
    leave the clock unmoved.

    FakeTicks.sleep_ms advances the clock instead of sleeping, so the sleep
    length is the distance the clock moved.
    """
    clock = FakeTicks(start_ms=1000)
    runner = Runner(ticks=clock)
    source = FakeButtonSource()
    button = Button(source=source, ticks=clock, long_press_ms=500)
    runner.add(button)

    source.press(at_ms=1000)
    now = runner.tick()
    assert now == 1000
    assert button.just_pressed is True

    runner.wait(now)
    assert clock.ticks_ms() == 1500

    runner.tick()
    assert button.just_long_pressed is True
