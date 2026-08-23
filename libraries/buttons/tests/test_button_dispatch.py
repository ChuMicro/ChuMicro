"""Cross-runtime tests for ``Button.handle``: which callbacks a tick earns.

Plain asserts, so they run on CPython (via pytest) and on
MicroPython/CircuitPython (via the lightweight test harness).  Every edge arrives
from ``FakeButtonSource`` and every duration is measured by ``FakeTicks``, so
nothing here reads a real clock or waits.
"""


from chumicro_buttons import Button
from chumicro_buttons.testing import FakeButtonSource
from chumicro_timing.testing import FakeTicks


class _CallLog:
    """Records callback dispatches in the order they arrive.

    The method signatures are the arity contract under test: ``click`` takes the
    press count and every other method takes nothing, so a dispatch with the
    wrong number of arguments raises ``TypeError`` instead of passing quietly.
    """

    def __init__(self) -> None:
        self.calls = []

    def press(self) -> None:
        """Record an ``on_press`` dispatch."""
        self.calls.append("press")

    def release(self) -> None:
        """Record an ``on_release`` dispatch."""
        self.calls.append("release")

    def long_press(self) -> None:
        """Record an ``on_long_press`` dispatch."""
        self.calls.append("long_press")

    def repeat(self) -> None:
        """Record an ``on_repeat`` dispatch."""
        self.calls.append("repeat")

    def click(self, count: int) -> None:
        """Record an ``on_click`` dispatch together with the count it carried."""
        self.calls.append(("click", count))


def _quiet_button(source, **options) -> Button:
    """Build a Button on ``source`` with long press, repeat, and clicks off.

    Each test turns back on only the timing it is about, so an unrelated event
    can never be what a tick reports.
    """
    settings = {"long_press_ms": 0, "repeat_ms": 0, "click_ms": 0}
    settings.update(options)
    return Button(source=source, ticks=FakeTicks(), **settings)


# -- handle() ----------------------------------------------------------


def test_handle_dispatches_exactly_the_callbacks_the_tick_earned() -> None:
    """Each tick calls only its own events, with on_click alone taking an argument."""
    source = FakeButtonSource()
    button = Button(
        source=source,
        ticks=FakeTicks(),
        long_press_ms=300,
        repeat_ms=200,
        repeat_delay_ms=300,
        click_ms=150,
    )
    call_log = _CallLog()
    button.on_press = call_log.press
    button.on_release = call_log.release
    button.on_long_press = call_log.long_press
    button.on_repeat = call_log.repeat
    button.on_click = call_log.click

    source.press(at_ms=0)
    button.check(0)
    button.handle(0)
    assert call_log.calls == ["press"]

    button.check(300)
    button.handle(300)
    assert call_log.calls == ["press", "long_press", "repeat"]

    source.release(at_ms=350)
    button.check(350)
    button.handle(350)
    assert call_log.calls == ["press", "long_press", "repeat", "release"]

    button.check(500)
    button.handle(500)
    button.check(600)
    button.handle(600)
    assert call_log.calls == ["press", "long_press", "repeat", "release"]


def test_a_tap_then_a_hold_dispatches_one_click_and_the_hold_earns_none() -> None:
    """on_click fires once for the tap; the hold that closed the series earns only on_long_press."""
    source = FakeButtonSource()
    button = Button(
        source=source,
        ticks=FakeTicks(),
        long_press_ms=500,
        repeat_ms=0,
        click_ms=300,
    )
    call_log = _CallLog()
    button.on_click = call_log.click
    button.on_long_press = call_log.long_press

    source.press(at_ms=0)
    button.check(0)
    button.handle(0)
    source.release(at_ms=50)
    button.check(50)
    button.handle(50)

    source.press(at_ms=100)
    button.check(100)
    button.handle(100)
    assert call_log.calls == []

    button.check(400)
    button.handle(400)
    assert call_log.calls == [("click", 1)]

    button.check(600)
    button.handle(600)
    assert call_log.calls == [("click", 1), "long_press"]

    source.release(at_ms=60000)
    button.check(60000)
    button.handle(60000)
    button.check(60300)
    button.handle(60300)
    assert call_log.calls == [("click", 1), "long_press"]


def test_handle_with_every_callback_left_as_none_raises_nothing() -> None:
    """A click, a press, a long press, a repeat, and a release all dispatch into no callbacks."""
    source = FakeButtonSource()
    button = Button(
        source=source,
        ticks=FakeTicks(),
        long_press_ms=200,
        repeat_ms=50,
        repeat_delay_ms=200,
        click_ms=100,
    )

    source.press(at_ms=0)
    button.check(0)
    button.handle(0)
    source.release(at_ms=50)
    button.check(50)
    button.handle(50)
    button.check(150)
    button.handle(150)
    assert button.just_clicked is True
    assert button.click_count == 1

    source.press(at_ms=200)
    button.check(200)
    button.handle(200)
    button.check(400)
    button.handle(400)
    assert button.just_long_pressed is True
    assert button.just_repeated is True

    source.release(at_ms=450)
    button.check(450)
    button.handle(450)
    assert button.just_released is True
    assert button.held_ms == 250
