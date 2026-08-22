"""Cross-runtime tests for ``FakeButtonSource``, the hand-driven edge source.

Plain asserts only, so they run on CPython (via pytest) and on
MicroPython/CircuitPython (via the lightweight test harness).  These drive the
fake directly rather than through a Button, so a change in the fake's own
contract is caught where it happens.
"""

from chumicro_buttons.testing import FakeButtonSource


def test_a_fresh_source_reports_one_key_and_no_edges() -> None:
    """The default source has one key, a clear overflow flag, and an empty queue."""
    source = FakeButtonSource()

    assert source.key_count == 1
    assert source.overflowed is False
    assert source.poll_calls == 0
    assert source.deinit_calls == 0
    assert source.next_event() is False


def test_the_key_count_is_whatever_the_test_asked_for() -> None:
    """A multi-key source reports the count a Buttons uses to build its keys."""
    source = FakeButtonSource(key_count=5)

    assert source.key_count == 5


def test_queued_edges_are_published_one_at_a_time_in_order() -> None:
    """next_event() publishes each edge on the event_* attributes, oldest first."""
    source = FakeButtonSource(key_count=2)
    source.press(key_index=1, at_ms=10)
    source.release(key_index=0, at_ms=25)

    assert source.next_event() is True
    assert source.event_key == 1
    assert source.event_pressed is True
    assert source.event_ms == 10

    assert source.next_event() is True
    assert source.event_key == 0
    assert source.event_pressed is False
    assert source.event_ms == 25

    assert source.next_event() is False


def test_press_and_release_default_to_key_zero_at_tick_zero() -> None:
    """Called with no arguments, press() queues an edge for key 0 stamped at 0 ms."""
    source = FakeButtonSource()
    source.press()

    assert source.next_event() is True
    assert source.event_key == 0
    assert source.event_pressed is True
    assert source.event_ms == 0


def test_poll_and_deinit_count_the_calls_the_button_made() -> None:
    """poll() and deinit() record how often they were asked, and queue nothing."""
    source = FakeButtonSource()

    source.poll(0)
    source.poll(10)
    source.deinit()

    assert source.poll_calls == 2
    assert source.deinit_calls == 1
    assert source.next_event() is False
