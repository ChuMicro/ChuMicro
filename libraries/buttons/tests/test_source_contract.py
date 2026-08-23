"""Cross-runtime tests for ``ButtonSource``, the contract every edge source honours.

Plain asserts plus the harness ``raises()`` helper, so they run on CPython
(via pytest) and on MicroPython/CircuitPython (via the lightweight test
harness).  The base class publishes the attributes a Button reads and refuses
the three methods a concrete source has to write, which is what keeps a
half-finished source from looking like a working one.
"""

from chumicro_buttons._adapters.base import ButtonSource
from chumicro_buttons.testing import FakeButtonSource
from chumicro_test_harness import raises


def test_the_contract_publishes_the_attributes_a_button_reads() -> None:
    """A bare source starts with no keys, no overflow, and an edge of key 0 at 0 ms."""
    source = ButtonSource()

    assert source.key_count == 0
    assert source.overflowed is False
    assert source.event_key == 0
    assert source.event_pressed is False
    assert source.event_ms == 0


def test_the_contract_refuses_the_methods_a_source_must_write() -> None:
    """poll(), next_event(), and deinit() raise NotImplementedError until overridden."""
    source = ButtonSource()

    with raises(NotImplementedError):
        source.poll(0)

    with raises(NotImplementedError):
        source.next_event()

    with raises(NotImplementedError):
        source.deinit()


def test_the_fake_source_answers_every_name_the_contract_declares() -> None:
    """FakeButtonSource carries the whole contract, so a Button cannot tell them apart."""
    fake = FakeButtonSource()

    for attribute_name in ("key_count", "overflowed", "event_key", "event_pressed", "event_ms"):
        assert hasattr(fake, attribute_name)

    assert fake.poll(0) is None
    assert fake.next_event() is False
    assert fake.deinit() is None
