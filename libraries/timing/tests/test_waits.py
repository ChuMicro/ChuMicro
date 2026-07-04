"""Cross-runtime tests for the completion-wait vocabulary: Signal + wait_for.

The generator is driven directly via ``.send()`` — the same protocol the
runner's wrapper uses — so these stay on the timing dependency floor and
never import the runner.  Plain asserts plus the harness ``raises()``
helper run them on CPython, MicroPython, and CircuitPython.
"""

import errno

from chumicro_test_harness import raises
from chumicro_timing.waits import Signal, wait_for

# -- Signal (the completion token) -----------------------------------


def test_signal_starts_unset_with_no_deadline() -> None:
    """A fresh Signal is unset, carries no value, and gates on no deadline."""
    signal = Signal()
    assert signal.is_set is False
    assert signal.value is None
    assert signal.ready(0) is False
    assert signal.next_deadline(0) is None


def test_signal_set_stores_value_and_marks_ready() -> None:
    """set(value) stores the value, flips is_set, and readies the wait."""
    signal = Signal()
    signal.set("192.0.2.7")
    assert signal.is_set is True
    assert signal.value == "192.0.2.7"
    assert signal.ready(0) is True


def test_signal_set_without_value_defaults_to_none() -> None:
    """set() with no argument completes with a None payload."""
    signal = Signal()
    signal.set()
    assert signal.is_set is True
    assert signal.value is None


def test_signal_clear_re_arms_for_reuse() -> None:
    """clear() drops the value and the set flag so one Signal serves many waits."""
    signal = Signal()
    signal.set("first")
    signal.clear()
    assert signal.is_set is False
    assert signal.value is None
    assert signal.ready(0) is False


# -- wait_for (the suspension helper) --------------------------------


def _run_until_yield(generator: object) -> object:
    """Prime a wait_for generator to its first suspension; return what it yields."""
    return generator.send(None)


def test_wait_for_returns_value_set_on_the_signal() -> None:
    """wait_for suspends until set, then returns the stored value."""
    signal = Signal()
    generator = wait_for(signal)
    yielded = _run_until_yield(generator)
    assert yielded is signal
    signal.set("ready")
    try:
        generator.send(0)
    except StopIteration as stop:
        assert stop.value == "ready"
    else:
        raise AssertionError("wait_for did not return after the signal was set")


def test_wait_for_parks_and_clears_the_deadline_on_the_signal() -> None:
    """wait_for reports its deadline via the signal while parked, then clears it."""
    signal = Signal()
    generator = wait_for(signal, deadline_ms=100)
    _run_until_yield(generator)
    assert signal.next_deadline(0) == 100
    signal.set("done")
    try:
        generator.send(50)
    except StopIteration:
        pass
    assert signal.next_deadline(0) is None


def test_wait_for_raises_etimedout_past_the_deadline() -> None:
    """Past deadline_ms with the signal unset, wait_for raises ETIMEDOUT inside the body."""
    signal = Signal()
    generator = wait_for(signal, deadline_ms=100)
    _run_until_yield(generator)
    with raises(OSError) as caught:
        generator.send(150)
    assert caught.value.args[0] == errno.ETIMEDOUT
    # The parked deadline is cleared on the way out.
    assert signal.next_deadline(0) is None


def test_wait_for_reuses_a_signal_after_clear() -> None:
    """One Signal serves sequential waits: set/return, clear, wait again."""
    signal = Signal()
    first = wait_for(signal)
    _run_until_yield(first)
    signal.set("one")
    try:
        first.send(0)
    except StopIteration as stop:
        assert stop.value == "one"
    signal.clear()
    second = wait_for(signal)
    _run_until_yield(second)
    signal.set("two")
    try:
        second.send(0)
    except StopIteration as stop:
        assert stop.value == "two"
