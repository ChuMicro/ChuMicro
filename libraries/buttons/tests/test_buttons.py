"""Cross-runtime tests for ``Buttons``: several keys on one source, ticked together.

Plain asserts plus the harness ``raises()`` helper, so they run on CPython
(via pytest) and on MicroPython/CircuitPython (via the lightweight test
harness).  Every edge arrives from ``FakeButtonSource`` and every duration is
measured by ``FakeTicks``, so nothing here reads a real clock or waits.
"""

from chumicro_buttons import Buttons
from chumicro_buttons.testing import FakeButtonSource
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks


class _PanelLog:
    """Records whole-panel dispatches together with the key index each one carried."""

    def __init__(self) -> None:
        self.calls = []

    def press(self, key_index: int) -> None:
        """Record an ``on_press`` dispatch for ``key_index``."""
        self.calls.append(("press", key_index))

    def release(self, key_index: int) -> None:
        """Record an ``on_release`` dispatch for ``key_index``."""
        self.calls.append(("release", key_index))


class _KeyLog:
    """Records the no-argument dispatches one key's own callbacks make."""

    def __init__(self) -> None:
        self.calls = []

    def press(self) -> None:
        """Record an ``on_press`` dispatch on the key that owns this log."""
        self.calls.append("press")

    def release(self) -> None:
        """Record an ``on_release`` dispatch on the key that owns this log."""
        self.calls.append("release")


def _quiet_panel(source, **options) -> Buttons:
    """Build a Buttons on ``source`` with long press, repeat, and clicks off.

    Each test turns back on only the timing it is about, so an unrelated event
    can never be what a tick reports.
    """
    settings = {"long_press_ms": 0, "repeat_ms": 0, "click_ms": 0}
    settings.update(options)
    return Buttons(source=source, ticks=FakeTicks(), **settings)


# -- Construction ------------------------------------------------------


def test_a_panel_with_neither_pins_nor_source_is_refused() -> None:
    """Buttons() with nothing to read raises ValueError naming both arguments."""
    with raises(ValueError, match="pins= or source="):
        Buttons()


def test_a_panel_given_an_empty_pin_sequence_is_refused() -> None:
    """An empty pins sequence is a config that resolved to nothing, not a zero-key panel."""
    with raises(ValueError, match="empty pins sequence"):
        Buttons(pins=())


def test_a_panel_has_one_button_per_key_in_pin_order() -> None:
    """len() reports the source's key count and indexing returns that key's Button."""
    source = FakeButtonSource(key_count=4)
    panel = _quiet_panel(source)

    assert len(panel) == 4
    assert panel[0] is panel.keys[0]
    assert panel[3] is panel.keys[3]
    assert panel[1] is not panel[2]


def test_a_key_taken_from_a_panel_refuses_to_be_ticked_on_its_own() -> None:
    """The panel's keys carry no source, so check() on one points back at the panel."""
    source = FakeButtonSource(key_count=2)
    panel = _quiet_panel(source)

    with raises(RuntimeError, match="tick the Buttons instead of the key"):
        panel[0].check(0)


# -- Per-key isolation and chords --------------------------------------


def test_pressing_one_key_leaves_the_others_alone() -> None:
    """Key 1 going down reports its own press and 20 ms held; key 0 reports nothing."""
    source = FakeButtonSource(key_count=2)
    panel = _quiet_panel(source)

    source.press(key_index=1, at_ms=100)

    assert panel.check(120) is True
    assert panel[1].pressed is True
    assert panel[1].just_pressed is True
    assert panel[1].held_ms == 20
    assert panel[0].pressed is False
    assert panel[0].just_pressed is False
    assert panel[0].held_ms == 0


def test_a_chord_lands_on_a_single_tick() -> None:
    """Two keys pressed between passes both report just_pressed on the tick that drains them."""
    source = FakeButtonSource(key_count=3)
    panel = _quiet_panel(source)

    source.press(key_index=0, at_ms=100)
    source.press(key_index=2, at_ms=105)

    assert panel.check(120) is True
    assert panel[0].just_pressed is True
    assert panel[2].just_pressed is True
    assert panel[1].just_pressed is False
    assert panel[0].held_ms == 20
    assert panel[2].held_ms == 15


def test_check_reports_news_from_any_key_and_silence_from_none() -> None:
    """check() is True on the tick one key moved and False on ticks where none did."""
    source = FakeButtonSource(key_count=2)
    panel = _quiet_panel(source)

    assert panel.check(0) is False

    source.press(key_index=1, at_ms=10)
    assert panel.check(10) is True

    assert panel.check(20) is False


# -- Callbacks ---------------------------------------------------------


def test_panel_callbacks_receive_the_key_index() -> None:
    """on_press and on_release are called with the number of the key that moved."""
    source = FakeButtonSource(key_count=3)
    panel = _quiet_panel(source)
    panel_log = _PanelLog()
    panel.on_press = panel_log.press
    panel.on_release = panel_log.release

    source.press(key_index=2, at_ms=0)
    panel.check(0)
    panel.handle(0)
    assert panel_log.calls == [("press", 2)]

    panel.check(10)
    panel.handle(10)
    assert panel_log.calls == [("press", 2)]

    source.release(key_index=2, at_ms=20)
    source.press(key_index=0, at_ms=20)
    panel.check(20)
    panel.handle(20)
    assert panel_log.calls == [("press", 2), ("press", 0), ("release", 2)]


def test_a_keys_own_callbacks_fire_through_the_panel_handle() -> None:
    """A callback set on one key runs when the panel is handled, with no panel callbacks set."""
    source = FakeButtonSource(key_count=2)
    panel = _quiet_panel(source)
    key_log = _KeyLog()
    panel[1].on_press = key_log.press
    panel[1].on_release = key_log.release

    source.press(key_index=1, at_ms=0)
    panel.check(0)
    panel.handle(0)
    source.release(key_index=1, at_ms=50)
    panel.check(50)
    panel.handle(50)

    assert key_log.calls == ["press", "release"]


# -- Shared settings, overflow, lifecycle ------------------------------


def test_the_panel_hands_its_timings_to_every_key() -> None:
    """A key built by the panel long-presses, repeats, and counts clicks as configured."""
    source = FakeButtonSource(key_count=2)
    panel = Buttons(
        source=source,
        ticks=FakeTicks(),
        long_press_ms=300,
        repeat_ms=100,
        repeat_delay_ms=300,
        click_ms=200,
    )

    source.press(key_index=1, at_ms=0)
    panel.check(0)
    source.release(key_index=1, at_ms=50)
    panel.check(50)

    assert panel.check(250) is True
    assert panel[1].just_clicked is True
    assert panel[1].click_count == 1

    source.press(key_index=0, at_ms=300)
    panel.check(300)

    assert panel.check(600) is True
    assert panel[0].just_long_pressed is True
    assert panel[0].just_repeated is True


def test_overflowed_propagates_to_the_panel_and_clears_the_source_flag() -> None:
    """The panel copies the source's overflowed flag, then resets it for the next tick."""
    source = FakeButtonSource(key_count=2)
    panel = _quiet_panel(source)
    source.overflowed = True

    panel.check(0)
    assert panel.overflowed is True
    assert source.overflowed is False

    panel.check(10)
    assert panel.overflowed is False


def test_panel_deinit_releases_the_shared_source() -> None:
    """One deinit() covers every key, because the keys share one source."""
    source = FakeButtonSource(key_count=3)
    panel = _quiet_panel(source)

    panel.deinit()

    assert source.deinit_calls == 1
