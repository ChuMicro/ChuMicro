"""Cross-runtime tests for ``Button`` holds: long press and auto-repeat.

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


# -- Long press --------------------------------------------------------


def test_long_press_fires_once_per_press_however_long_the_key_is_held() -> None:
    """Holding across twenty ticks past the threshold yields one just_long_pressed."""
    source = FakeButtonSource()
    button = _quiet_button(source, long_press_ms=500)
    source.press(at_ms=0)

    fired_at = []
    for tick_ms in range(0, 2001, 100):
        button.check(tick_ms)
        if button.just_long_pressed:
            fired_at.append(tick_ms)

    assert fired_at == [500]


def test_long_press_re_arms_for_the_next_press() -> None:
    """Releasing and pressing again earns a second just_long_pressed."""
    source = FakeButtonSource()
    button = _quiet_button(source, long_press_ms=500)
    source.press(at_ms=0)
    button.check(0)
    button.check(500)
    assert button.just_long_pressed is True

    source.release(at_ms=600)
    button.check(600)
    source.press(at_ms=700)
    button.check(700)
    assert button.just_long_pressed is False

    assert button.check(1200) is True
    assert button.just_long_pressed is True


def test_long_press_ms_zero_disables_long_press() -> None:
    """With long_press_ms=0 a minute-long hold never fires just_long_pressed."""
    source = FakeButtonSource()
    button = _quiet_button(source, long_press_ms=0)
    source.press(at_ms=0)

    for tick_ms in (0, 500, 5000, 60000):
        assert button.check(tick_ms) is (tick_ms == 0)
        assert button.just_long_pressed is False


# -- Auto-repeat -------------------------------------------------------


def test_repeat_starts_after_the_delay_and_then_keeps_the_cadence() -> None:
    """The first repeat lands at repeat_delay_ms and the rest every repeat_ms after."""
    source = FakeButtonSource()
    button = _quiet_button(source, repeat_ms=100, repeat_delay_ms=500)
    source.press(at_ms=0)

    fired_at = []
    for tick_ms in range(0, 901, 50):
        button.check(tick_ms)
        if button.just_repeated:
            fired_at.append(tick_ms)

    assert fired_at == [500, 600, 700, 800, 900]


def test_repeat_keeps_its_schedule_on_a_loop_that_ticks_off_the_cadence() -> None:
    """Every repeat lands on the first tick at or after its own deadline, so nothing drifts.

    The deadlines stay at repeat_delay_ms plus whole multiples of repeat_ms even
    though no tick of this 30 ms loop lands on most of them, which is what stops a
    slow loop from stretching the cadence a little further apart on every fire.
    """
    source = FakeButtonSource()
    button = _quiet_button(source, repeat_ms=100, repeat_delay_ms=500)
    source.press(at_ms=0)

    loop_period_ms = 30
    fired_at = []
    for tick_ms in range(0, 1501, loop_period_ms):
        button.check(tick_ms)
        if button.just_repeated:
            fired_at.append(tick_ms)

    deadlines = list(range(500, 1501, 100))
    assert len(fired_at) == len(deadlines)
    for fire_index in range(len(deadlines)):
        deadline_ms = deadlines[fire_index]
        assert deadline_ms <= fired_at[fire_index] < deadline_ms + loop_period_ms


def test_a_stall_collapses_the_repeats_it_covered_into_a_single_fire() -> None:
    """A two-second gap between ticks fires one repeat, not one per period it spanned."""
    source = FakeButtonSource()
    button = _quiet_button(source, repeat_ms=100, repeat_delay_ms=100)
    source.press(at_ms=0)

    fire_count = 0
    for tick_ms in (0, 100, 2100):
        button.check(tick_ms)
        if button.just_repeated:
            fire_count += 1

    assert fire_count == 2

    assert button.check(2150) is False
    assert button.just_repeated is False

    assert button.check(2200) is True
    assert button.just_repeated is True


def test_repeat_stops_on_release_and_waits_out_the_delay_again() -> None:
    """A release ends the cadence, and the next press restarts it from its own delay."""
    source = FakeButtonSource()
    button = _quiet_button(source, repeat_ms=100, repeat_delay_ms=500)
    source.press(at_ms=0)
    button.check(0)
    button.check(500)
    assert button.just_repeated is True

    source.release(at_ms=550)
    button.check(600)
    assert button.just_repeated is False
    assert button.check(700) is False

    source.press(at_ms=800)
    button.check(800)
    assert button.just_repeated is False
    assert button.check(1299) is False
    assert button.check(1300) is True
    assert button.just_repeated is True


def test_repeat_ms_zero_disables_repeat() -> None:
    """With repeat_ms=0 a hold well past repeat_delay_ms never fires just_repeated."""
    source = FakeButtonSource()
    button = _quiet_button(source, repeat_ms=0, repeat_delay_ms=100)
    source.press(at_ms=0)

    for tick_ms in (0, 100, 200, 1000):
        button.check(tick_ms)
        assert button.just_repeated is False
