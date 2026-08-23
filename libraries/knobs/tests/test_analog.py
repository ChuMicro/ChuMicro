"""Analog knob semantics: deadband, step quantization, direction, and dispatch.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""

from chumicro_knobs import DEFAULT_DEADBAND, DEFAULT_STEPS, RAW_RANGE, AnalogKnob
from chumicro_knobs.testing import FakeAnalogSource
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- construction --


def test_the_default_deadband_stays_under_one_step() -> None:
    """512 counts is smaller than the 655 a step spans at 100 steps, so no step is stranded."""
    assert DEFAULT_DEADBAND < RAW_RANGE // DEFAULT_STEPS


def test_building_without_a_pin_or_source_refuses() -> None:
    """An AnalogKnob with nothing to sample raises ValueError naming both ways to give it one."""
    with raises(ValueError, match="source"):
        AnalogKnob()


def test_readings_start_at_the_bottom_of_the_sweep() -> None:
    """A fresh knob reports step 0 and no movement until something is sampled."""
    knob = AnalogKnob(source=FakeAnalogSource())

    assert knob.value == 0
    assert knob.raw == 0
    assert knob.delta == 0
    assert knob.just_moved is False


# -- deadband --


def test_a_reading_inside_the_deadband_changes_nothing() -> None:
    """A move of exactly the deadband is wander, so value, raw, and delta all hold."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(DEFAULT_DEADBAND)

    assert knob.check(0) is False
    assert knob.value == 0
    assert knob.raw == 0
    assert knob.delta == 0
    assert knob.just_moved is False


def test_one_count_past_the_deadband_settles_the_raw_reading() -> None:
    """Clearing the deadband moves raw even when the step it lands in is the same one."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(DEFAULT_DEADBAND + 1)

    assert knob.check(0) is False
    assert knob.raw == DEFAULT_DEADBAND + 1
    assert knob.value == 0
    assert knob.just_moved is False


def test_dither_around_a_settled_reading_never_moves_the_value() -> None:
    """Ten samples wandering inside the deadband leave the settled reading exactly as it was."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(32768)
    knob.check(0)

    wander = 0
    while wander < 10:
        source.set_raw(32768 + (wander * 100) - 400)
        assert knob.check(10 + wander) is False
        wander += 1

    assert knob.value == 50
    assert knob.raw == 32768


def test_a_smaller_deadband_lets_a_smaller_move_through() -> None:
    """deadband=0 follows every sample, which is the setting for an already-clean signal."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source, deadband=0)

    source.set_raw(1)
    knob.check(0)

    assert knob.raw == 1


# -- steps --


def test_the_middle_of_the_sweep_is_the_middle_step() -> None:
    """Half of full scale reads as step 50 of the default 100."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(RAW_RANGE // 2)

    assert knob.check(0) is True
    assert knob.value == 50
    assert knob.delta == 50
    assert knob.just_moved is True


def test_the_top_of_the_sweep_is_the_last_step() -> None:
    """Full scale reads as steps - 1, so the reading never runs off the end."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(RAW_RANGE - 1)
    knob.check(0)

    assert knob.value == DEFAULT_STEPS - 1


def test_steps_sets_how_many_positions_the_sweep_reports() -> None:
    """steps=10 turns half of full scale into step 5."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source, steps=10)

    source.set_raw(RAW_RANGE // 2)
    knob.check(0)

    assert knob.value == 5


def test_turning_the_knob_down_reports_a_negative_delta() -> None:
    """Going from step 50 to step 25 reports delta -25."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(RAW_RANGE // 2)
    knob.check(0)

    source.set_raw(RAW_RANGE // 4)
    knob.check(10)

    assert knob.value == 25
    assert knob.delta == -25


def test_a_still_knob_reports_nothing_on_the_next_tick() -> None:
    """The tick after a move clears delta and just_moved and gates handle off."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(RAW_RANGE // 2)
    knob.check(0)

    assert knob.check(10) is False
    assert knob.delta == 0
    assert knob.just_moved is False
    assert knob.value == 50


def test_the_tick_timestamp_reaches_the_source() -> None:
    """check hands the loop's shared timestamp to the source instead of fetching one."""
    ticks = FakeTicks()
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    ticks.advance(750)
    knob.check(ticks.ticks_ms())

    assert source.poll_calls == 1
    assert source.last_poll_ms == 750


def test_a_source_can_start_parked_somewhere() -> None:
    """A source built at full scale reads as the last step on its first tick."""
    knob = AnalogKnob(source=FakeAnalogSource(raw=RAW_RANGE - 1))

    knob.check(0)

    assert knob.value == DEFAULT_STEPS - 1


# -- dispatch --


def test_handle_calls_on_change_with_the_new_step() -> None:
    """on_change receives the step the knob now points at, once per tick that moved."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)
    seen = []
    knob.on_change = seen.append

    source.set_raw(RAW_RANGE // 2)
    knob.check(0)
    knob.handle(0)

    source.set_raw(RAW_RANGE // 4)
    knob.check(10)
    knob.handle(10)

    assert seen == [50, 25]


def test_handle_stays_quiet_on_a_still_tick() -> None:
    """A tick with no movement calls no callback."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)
    seen = []
    knob.on_change = seen.append

    knob.check(0)
    knob.handle(0)

    assert seen == []


def test_handle_is_safe_with_no_callback_assigned() -> None:
    """Moving with on_change left unset updates the reading and raises nothing."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    source.set_raw(RAW_RANGE // 2)
    knob.check(0)
    knob.handle(0)

    assert knob.value == 50


def test_deinit_releases_the_source() -> None:
    """deinit passes through to the source so the pin comes back."""
    source = FakeAnalogSource()
    knob = AnalogKnob(source=source)

    knob.deinit()

    assert source.deinit_calls == 1
