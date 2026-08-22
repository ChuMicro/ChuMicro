"""Encoder semantics: detent accumulation, direction, bounds, wrap, and dispatch.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""

from chumicro_knobs import DEFAULT_DETENT_STEPS, Encoder
from chumicro_knobs.testing import FakeEncoderSource
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

# -- construction --


def test_detent_steps_defaults_to_four() -> None:
    """The shipped default matches an encoder with one click per quadrature cycle."""
    assert DEFAULT_DETENT_STEPS == 4


def test_building_without_pins_or_source_refuses() -> None:
    """An Encoder with nothing to read raises ValueError naming both ways to give it one."""
    with raises(ValueError, match="source"):
        Encoder()


def test_building_with_one_pin_refuses() -> None:
    """Quadrature needs two pins, so pin_a alone raises ValueError."""
    with raises(ValueError, match="pin_b"):
        Encoder(object())


def test_wrap_without_bounds_refuses() -> None:
    """wrap=True with no bounds has nothing to wrap around, so it raises ValueError."""
    with raises(ValueError, match="bounds"):
        Encoder(source=FakeEncoderSource(), wrap=True)


def test_position_starts_at_zero_when_unbounded() -> None:
    """A free-running encoder starts counting from zero with no movement reported."""
    encoder = Encoder(source=FakeEncoderSource())

    assert encoder.position == 0
    assert encoder.delta == 0
    assert encoder.just_moved is False


def test_position_starts_at_the_low_bound_when_the_range_is_above_zero() -> None:
    """bounds=(5, 9) puts the starting position at 5 rather than out of range at 0."""
    encoder = Encoder(source=FakeEncoderSource(), bounds=(5, 9))

    assert encoder.position == 5


def test_position_starts_at_the_high_bound_when_the_range_is_below_zero() -> None:
    """bounds=(-9, -5) puts the starting position at -5 rather than out of range at 0."""
    encoder = Encoder(source=FakeEncoderSource(), bounds=(-9, -5))

    assert encoder.position == -5


def test_a_source_already_turned_is_the_starting_point() -> None:
    """A source built with a count already on it reports no movement on the first tick."""
    encoder = Encoder(source=FakeEncoderSource(raw_position=17))

    assert encoder.check(0) is False
    assert encoder.position == 0


# -- turning --


def test_turning_forward_moves_the_position() -> None:
    """Three detents forward move position to 3, with delta 3 on that tick."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(3)

    assert encoder.check(0) is True
    assert encoder.position == 3
    assert encoder.delta == 3
    assert encoder.just_moved is True


def test_turning_backward_moves_the_position_the_other_way() -> None:
    """Two detents backward take position to -2 with delta -2."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(-2)
    encoder.check(0)

    assert encoder.position == -2
    assert encoder.delta == -2


def test_a_still_shaft_reports_nothing() -> None:
    """A tick with no turning clears delta and just_moved and gates handle off."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(1)
    encoder.check(0)

    assert encoder.check(10) is False
    assert encoder.delta == 0
    assert encoder.just_moved is False
    assert encoder.position == 1


def test_movement_accumulates_across_ticks() -> None:
    """Two ticks of one detent each leave position at 2 with delta 1 on each tick."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(1)
    encoder.check(0)
    assert encoder.delta == 1

    source.turn(1)
    encoder.check(10)

    assert encoder.delta == 1
    assert encoder.position == 2


def test_several_turns_before_one_tick_arrive_together() -> None:
    """A loop that stalled sees the whole spin on the tick it finally reaches."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(4)
    source.turn(3)
    encoder.check(0)

    assert encoder.delta == 7
    assert encoder.position == 7


def test_reversing_direction_reverses_the_delta() -> None:
    """Turning forward then back reports a positive delta then a negative one."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(5)
    encoder.check(0)
    assert encoder.delta == 5

    source.turn(-8)
    encoder.check(10)

    assert encoder.delta == -8
    assert encoder.position == -3


def test_the_tick_timestamp_reaches_the_source() -> None:
    """check hands the loop's shared timestamp to the source instead of fetching one."""
    ticks = FakeTicks()
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    ticks.advance(250)
    encoder.check(ticks.ticks_ms())

    assert source.poll_calls == 1
    assert source.last_poll_ms == 250


# -- bounds --


def test_position_stops_at_the_high_bound() -> None:
    """Turning past bounds=(0, 5) leaves position at 5 and reports only the part that fit."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 5))

    source.turn(8)
    encoder.check(0)

    assert encoder.position == 5
    assert encoder.delta == 5


def test_position_stops_at_the_low_bound() -> None:
    """Turning past the bottom of bounds=(0, 5) leaves position at 0."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 5))

    source.turn(-3)
    encoder.check(0)

    assert encoder.position == 0
    assert encoder.delta == 0


def test_turning_a_pinned_knob_further_reports_nothing() -> None:
    """Held against the high bound, more turning reports delta 0 and gates handle off."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 5))

    source.turn(5)
    encoder.check(0)

    source.turn(4)

    assert encoder.check(10) is False
    assert encoder.position == 5
    assert encoder.delta == 0
    assert encoder.just_moved is False


def test_turning_back_off_a_bound_answers_at_once() -> None:
    """Over-turning past a bound does not bank up: one detent back moves position by one."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 5))

    source.turn(20)
    encoder.check(0)

    source.turn(-1)
    encoder.check(10)

    assert encoder.position == 4
    assert encoder.delta == -1


def test_a_bounded_knob_still_moves_inside_its_range() -> None:
    """A turn that fits inside bounds lands exactly where an unbounded one would."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 100))

    source.turn(37)
    encoder.check(0)

    assert encoder.position == 37
    assert encoder.delta == 37


# -- wrap --


def test_wrap_carries_past_the_high_bound() -> None:
    """On bounds=(0, 3) with wrap, five detents forward land on 1 and report delta 5."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 3), wrap=True)

    source.turn(5)
    encoder.check(0)

    assert encoder.position == 1
    assert encoder.delta == 5


def test_wrap_carries_past_the_low_bound() -> None:
    """One detent back from the bottom of bounds=(0, 3) lands on 3."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(0, 3), wrap=True)

    source.turn(-1)
    encoder.check(0)

    assert encoder.position == 3
    assert encoder.delta == -1


def test_wrap_works_on_a_range_that_does_not_start_at_zero() -> None:
    """On bounds=(10, 12) with wrap, one detent past 12 lands on 10."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source, bounds=(10, 12), wrap=True)

    source.turn(3)
    encoder.check(0)

    assert encoder.position == 10
    assert encoder.delta == 3


# -- dispatch --


def test_handle_calls_on_change_with_the_detent_change() -> None:
    """on_change receives the signed delta for the tick, once per tick that moved."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)
    changes = []
    encoder.on_change = changes.append

    source.turn(2)
    encoder.check(0)
    encoder.handle(0)

    source.turn(-1)
    encoder.check(10)
    encoder.handle(10)

    assert changes == [2, -1]


def test_handle_stays_quiet_on_a_still_tick() -> None:
    """A tick with no turning calls no callback."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)
    changes = []
    encoder.on_change = changes.append

    encoder.check(0)
    encoder.handle(0)

    assert changes == []


def test_handle_is_safe_with_no_callback_assigned() -> None:
    """Turning with on_change left unset moves the position and raises nothing."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    source.turn(1)
    encoder.check(0)
    encoder.handle(0)

    assert encoder.position == 1


def test_deinit_releases_the_source() -> None:
    """deinit passes through to the source so the pins come back."""
    source = FakeEncoderSource()
    encoder = Encoder(source=source)

    encoder.deinit()

    assert source.deinit_calls == 1
