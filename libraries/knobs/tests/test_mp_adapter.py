"""Tests for the MicroPython sources: the quadrature decode, one edge at a time.

The shaft, the two pins under it, and the ``machine`` stub that lets the source import off
a board all live in ``_mp_helpers``.  What that buys is the one property a board test
cannot show cheaply: the decode replayed edge by edge, with the shaft parked anywhere in
its cycle, turned either way, wobbled on a boundary the way a worn detent wobbles, and fed
the both-pins-at-once transition a noisy encoder produces.  Real pins, real interrupt
latency, and real contact bounce stay in ``functional_tests/``.

The module under test is MicroPython-marked, so a CircuitPython deploy never carries it;
this file stays on the host lane where importing it always resolves.
"""

#: Host-lane only: imports a MicroPython-marked module, which a CircuitPython
#: deploy does not carry.  Never staged to a device.
__chumicro_host_only__ = True

from _mp_helpers import (
    BANKED_STEPS,
    DETENTS,
    FORWARD_CYCLE,
    IMPOSSIBLE_JUMPS,
    LAST_STATE,
    QUADRATURE_STEPS,
    FakeConverter,
    MpAnalogSource,
    PinType,
    Shaft,
    const,
)

# -- the decode table --


def test_the_decode_table_answers_for_every_pair_of_pin_states() -> None:
    """Sixteen entries: four states the shaft was in, times four it could read as now.

    The index the handler builds is ``(previous << 2) | current``, so a table any shorter
    would index off the end on a state pair nobody thought about.
    """
    assert len(QUADRATURE_STEPS) == 16


# -- turning the shaft --


def test_a_forward_turn_counts_a_detent_every_four_steps() -> None:
    """Twelve quadrature steps forward are three detents at the default divisor."""
    shaft = Shaft()

    shaft.turn(12)

    assert shaft.counted() == 3


def test_the_same_turn_backward_counts_the_matching_amount_down() -> None:
    """The identical run of steps the other way round is three detents below zero."""
    shaft = Shaft()

    shaft.turn(-12)

    assert shaft.counted() == -3


def test_turning_back_to_where_it_started_leaves_nothing_banked() -> None:
    """Out and back is a net zero with no part-detent left over, at any distance.

    Seven steps out is one detent counted and three still banked, so the return trip has
    to spend those three before it can count anything down.  A decode that dropped the
    banked steps on a reversal would report a detent the wrist never felt.
    """
    for steps in (1, 3, 4, 5, 7, 12):
        shaft = Shaft()

        shaft.turn(steps)
        shaft.turn(-steps)

        assert shaft.counted() == 0
        assert shaft.banked() == 0


def test_the_detents_and_the_banked_steps_always_add_back_up_to_the_turn() -> None:
    """Detents times the divisor, plus what is banked, is the run of steps that went in.

    This is the whole contract of the decode in one line, checked across divisors and in
    both directions: nothing invented and nothing dropped, whatever the shaft did.
    """
    for detent_steps in (1, 2, 4, 6):
        for steps in (0, 1, 3, 4, 5, 7, 12, -1, -3, -4, -5, -7, -12):
            shaft = Shaft(detent_steps=detent_steps)

            shaft.turn(steps)

            assert shaft.counted() * detent_steps + shaft.banked() == steps


def test_the_shaft_can_be_parked_anywhere_in_its_cycle() -> None:
    """A source built while the shaft sat mid-cycle still counts its first detent right.

    Construction samples both pins, so the first edge is read against where the shaft
    actually was.  Read against a made-up starting state it could count a detent that
    never happened, which is what a knob does when it jumps on the first touch.
    """
    for state in FORWARD_CYCLE:
        shaft = Shaft(state)

        assert shaft.slots()[LAST_STATE] == (state[0] << 1) | state[1]

        shaft.turn(4)

        assert shaft.counted() == 1


# -- the shaft that does not turn cleanly --


def test_a_shaft_wobbling_on_one_boundary_invents_no_detents() -> None:
    """A shaft resting between detents and rocking one step each way counts nothing.

    This is the dirty-encoder case: a worn detent lets the shaft rock across a single
    quadrature boundary without the wrist moving.  Every rock forward is undone by the
    rock back, so the count has to stay where it was however long it goes on.
    """
    shaft = Shaft()

    for _ in range(20):
        shaft.turn(1)
        shaft.turn(-1)

    assert shaft.counted() == 0
    assert shaft.banked() == 0


def test_a_wobble_just_past_a_detent_does_not_count_it_twice() -> None:
    """Rocking on the boundary a detent just fired on leaves that detent counted once.

    Counting the detent resets the banked steps, so the rock back stands one step short
    of the boundary rather than on top of it, and rocking forward again only re-reaches
    zero instead of earning a second detent.
    """
    shaft = Shaft()
    shaft.turn(4)

    for _ in range(20):
        shaft.turn(-1)
        shaft.turn(1)

    assert shaft.counted() == 1
    assert shaft.banked() == 0


def test_both_pins_changing_at_once_reads_as_no_movement() -> None:
    """The four transitions a turning shaft cannot make bank nothing and count nothing.

    Only noise reaches these, and there is no direction to read out of them: the shaft is
    equally far around the cycle either way.  Guessing one is how a dirty encoder invents
    detents, so the table answers all four with a standstill.
    """
    for start, landing in IMPOSSIBLE_JUMPS:
        shaft = Shaft(start)

        shaft.move_to(landing)

        assert shaft.counted() == 0
        assert shaft.banked() == 0


def test_a_repeated_reading_of_the_same_state_is_a_standstill() -> None:
    """An edge that leaves the pins where they were moves nothing.

    A hard interrupt can arrive after the pin has already bounced back, so the handler
    reads the state it recorded last time and has to answer that with a standstill.
    """
    shaft = Shaft()

    for _ in range(8):
        shaft.move_to((1, 1))

    assert shaft.counted() == 0
    assert shaft.banked() == 0


# -- how far a detent is --


def test_a_divisor_of_one_counts_every_step_as_a_detent() -> None:
    """A smooth shaft with no clicks reports every quadrature step, both directions."""
    shaft = Shaft(detent_steps=1)

    shaft.turn(7)
    assert shaft.counted() == 7

    shaft.turn(-9)
    assert shaft.counted() == -2


def test_the_default_divisor_holds_three_steps_back_before_the_fourth_lands() -> None:
    """Nothing is published until the fourth step, then all four arrive as one detent."""
    shaft = Shaft()

    for step in (1, 2, 3):
        shaft.turn(1)
        assert shaft.counted() == 0
        assert shaft.banked() == step

    shaft.turn(1)

    assert shaft.counted() == 1
    assert shaft.banked() == 0


# -- the slots the interrupt writes --


def test_the_interrupt_writes_the_three_slots_it_was_given() -> None:
    """Detents, banked steps, and the last pin state, in that order and nowhere else.

    The array is sized once at construction so the handler never has to grow it, which
    makes these three slots the whole of what an interrupt is allowed to touch.
    """
    shaft = Shaft()

    assert shaft.slots() == (0, 0, 0b11)

    shaft.turn(5)
    slots = shaft.slots()

    assert len(slots) == 3
    assert slots[DETENTS] == 1
    assert slots[BANKED_STEPS] == 1
    assert slots[LAST_STATE] == 0b01


def test_the_count_the_loop_reads_is_the_one_the_interrupt_left() -> None:
    """raw_position only moves on a poll, so a tick sees one count for its whole pass.

    The interrupt keeps counting while the loop is elsewhere; poll is where that count
    crosses into normal context.
    """
    shaft = Shaft()
    shaft.source.poll(0)

    shaft.turn(8)

    assert shaft.source.raw_position == 0

    shaft.source.poll(1)

    assert shaft.source.raw_position == 2


# -- setting up and letting go --


def test_both_pins_are_watched_on_both_edges_from_inside_the_interrupt() -> None:
    """Rising and falling on each pin, handled hard, which is what catches a fast spin.

    Half the quadrature steps are falling edges and half are rising, so watching one
    direction would halve the count; and a scheduled handler runs when the interpreter
    next reaches a safe point, by which time a fast spin has moved on.
    """
    shaft = Shaft()
    both_edges = PinType.IRQ_RISING | PinType.IRQ_FALLING

    for pin in (shaft.pin_a, shaft.pin_b):
        assert pin.mode == PinType.IN
        assert pin.pull == PinType.PULL_UP
        assert pin.trigger == both_edges
        assert pin.handler is not None


def test_deinit_takes_the_handler_off_both_pins() -> None:
    """After teardown the shaft can turn as far as it likes and nothing counts it."""
    shaft = Shaft()

    shaft.source.deinit()

    assert shaft.pin_a.handler is None
    assert shaft.pin_b.handler is None

    shaft.turn(12)

    assert shaft.counted() == 0


# -- the wiper --


def test_the_converter_reads_once_on_construction_and_once_on_every_poll() -> None:
    """A knob built mid-turn starts from where the wiper already sits, not from zero."""
    converter = FakeConverter(reading=41_000)
    source = MpAnalogSource(converter)

    assert source.raw == 41_000
    assert converter.conversions == 1

    converter.reading = 12_500
    source.poll(0)

    assert source.raw == 12_500
    assert converter.conversions == 2


def test_the_converter_has_no_pin_to_hand_back() -> None:
    """deinit is a no-op that exists so a knob tears down the same way on either runtime."""
    source = MpAnalogSource(FakeConverter())

    assert source.deinit() is None


# -- the runtime this module expects --


def test_const_hands_its_value_straight_back_whichever_one_this_runtime_bound() -> None:
    """``const`` returns what it was given, from ``micropython`` or from the fallback.

    On a board it is a compiler hint that folds the value into the bytecode.  A host has
    no ``micropython`` module to import it from, so the module defines a plain function
    instead, and that fallback is what lets everything above import at all.
    """
    assert const(7) == 7
