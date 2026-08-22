"""Cross-runtime tests for ``Button`` edges: what one tick makes of the source's news.

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


# -- Edges carry their own timestamps --------------------------------


def test_press_is_timed_from_its_own_stamp_not_the_tick_that_noticed_it() -> None:
    """A press stamped at 100 ms and first seen at 120 ms reports 20 ms held, not 0.

    Capture is the whole point of the design: the edge happened while the loop
    was elsewhere, and the hold the user performed starts at the edge.
    """
    source = FakeButtonSource()
    button = _quiet_button(source)

    source.press(at_ms=100)

    assert button.check(120) is True
    assert button.just_pressed is True
    assert button.pressed is True
    assert button.held_ms == 20


def test_a_long_press_is_earned_by_the_edge_time_a_stalled_loop_missed() -> None:
    """A press stamped 600 ms before the tick that drains it long-presses immediately."""
    source = FakeButtonSource()
    button = _quiet_button(source, long_press_ms=500)

    source.press(at_ms=100)

    assert button.check(700) is True
    assert button.held_ms == 600
    assert button.just_long_pressed is True


# -- The just_* family -----------------------------------------------


def test_just_flags_are_true_only_on_the_tick_the_thing_happened() -> None:
    """A tick with no new edges clears every just_* flag and leaves pressed True."""
    source = FakeButtonSource()
    button = _quiet_button(source)
    source.press(at_ms=100)
    button.check(100)

    assert button.check(150) is False
    assert button.just_pressed is False
    assert button.just_released is False
    assert button.just_long_pressed is False
    assert button.just_repeated is False
    assert button.just_clicked is False
    assert button.pressed is True
    assert button.held_ms == 50


def test_a_release_leaves_held_ms_holding_the_press_duration() -> None:
    """The release edge drops pressed and leaves held_ms at how long the press lasted.

    The duration is measured edge to edge, so an on_release handler reads the hold
    the user performed rather than the gap to the tick that noticed the release.
    """
    source = FakeButtonSource()
    button = _quiet_button(source)
    source.press(at_ms=0)
    button.check(0)
    button.check(100)
    assert button.held_ms == 100

    source.release(at_ms=150)

    assert button.check(160) is True
    assert button.just_released is True
    assert button.pressed is False
    assert button.held_ms == 150

    button.check(400)
    assert button.held_ms == 150

    source.press(at_ms=500)
    button.check(500)
    assert button.held_ms == 0


def test_a_press_matching_the_current_level_is_ignored() -> None:
    """A second press edge while the key is already down reports no news at all."""
    source = FakeButtonSource()
    button = _quiet_button(source)
    source.press(at_ms=0)
    button.check(0)

    source.press(at_ms=50)

    assert button.check(60) is False
    assert button.just_pressed is False
    assert button.pressed is True
    assert button.held_ms == 60


def test_a_release_matching_the_current_level_is_ignored() -> None:
    """A release edge while the key is already up reports no news at all."""
    source = FakeButtonSource()
    button = _quiet_button(source)

    source.release(at_ms=10)

    assert button.check(20) is False
    assert button.just_released is False
    assert button.pressed is False


# -- held_ms -----------------------------------------------------------


def test_held_ms_is_zero_while_the_key_is_up() -> None:
    """Ticking an untouched button leaves held_ms at 0 and reports no news."""
    source = FakeButtonSource()
    button = _quiet_button(source)

    assert button.check(500) is False
    assert button.held_ms == 0


def test_held_ms_never_goes_negative() -> None:
    """Edges stamped out of order clamp held_ms at 0 rather than reporting a negative hold."""
    source = FakeButtonSource()
    button = _quiet_button(source)

    source.press(at_ms=200)
    button.check(150)
    assert button.pressed is True
    assert button.held_ms == 0

    source.release(at_ms=100)
    button.check(250)
    assert button.pressed is False
    assert button.held_ms == 0


def test_a_lone_button_ignores_edges_belonging_to_another_key() -> None:
    """A lone Button owns key 0, so a multi-key source's other keys are not its news."""
    source = FakeButtonSource(key_count=2)
    button = _quiet_button(source)

    source.press(key_index=1, at_ms=0)

    assert button.check(10) is False
    assert button.pressed is False
    assert button.just_pressed is False

    source.press(key_index=1, at_ms=20)
    source.press(key_index=0, at_ms=20)

    assert button.check(30) is True
    assert button.just_pressed is True
    assert button.held_ms == 10


def test_check_polls_the_source_once_per_tick() -> None:
    """Every check() asks the source to capture, whether or not an edge follows."""
    source = FakeButtonSource()
    button = _quiet_button(source)

    button.check(0)
    button.check(10)

    assert source.poll_calls == 2


# -- Overflow ----------------------------------------------------------


def test_overflowed_propagates_from_the_source_and_clears_its_flag() -> None:
    """The button copies the source's overflowed flag, then resets it for the next tick."""
    source = FakeButtonSource()
    button = _quiet_button(source)
    source.overflowed = True

    button.check(0)
    assert button.overflowed is True
    assert source.overflowed is False

    button.check(10)
    assert button.overflowed is False
