"""The two source contracts and the hand-driven fakes that stand in for hardware.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).
"""

from chumicro_knobs._adapters.base import AnalogSource, EncoderSource
from chumicro_knobs.testing import FakeAnalogSource, FakeEncoderSource
from chumicro_test_harness import raises

# -- the contracts --


def test_an_encoder_source_starts_its_count_at_zero() -> None:
    """The contract publishes raw_position so a knob can read it without a method call."""
    assert EncoderSource.raw_position == 0


def test_an_analog_source_starts_its_reading_at_zero() -> None:
    """The contract publishes raw so a knob can read it without a method call."""
    assert AnalogSource.raw == 0


def test_the_encoder_contract_leaves_capture_to_the_runtime() -> None:
    """Both encoder contract methods refuse until a per-runtime source implements them."""
    contract = EncoderSource()

    with raises(NotImplementedError):
        contract.poll(0)
    with raises(NotImplementedError):
        contract.deinit()


def test_the_analog_contract_leaves_conversion_to_the_runtime() -> None:
    """Both analog contract methods refuse until a per-runtime source implements them."""
    contract = AnalogSource()

    with raises(NotImplementedError):
        contract.poll(0)
    with raises(NotImplementedError):
        contract.deinit()


# -- the fakes --


def test_turning_the_encoder_fake_adds_up() -> None:
    """turn moves the count in both directions and leaves the total behind."""
    source = FakeEncoderSource()

    source.turn(4)
    source.turn(-1)

    assert source.raw_position == 3


def test_the_encoder_fake_can_start_from_a_count() -> None:
    """A starting raw_position stands in for a source built while the shaft was elsewhere."""
    assert FakeEncoderSource(raw_position=-6).raw_position == -6


def test_the_encoder_fake_records_what_was_asked_of_it() -> None:
    """poll and deinit both keep a tally a test can assert against."""
    source = FakeEncoderSource()

    source.poll(40)
    source.poll(80)
    source.deinit()

    assert source.poll_calls == 2
    assert source.last_poll_ms == 80
    assert source.deinit_calls == 1


def test_setting_the_analog_fake_parks_the_wiper() -> None:
    """set_raw replaces the reading rather than adding to it."""
    source = FakeAnalogSource(raw=100)

    source.set_raw(4000)

    assert source.raw == 4000


def test_the_analog_fake_records_what_was_asked_of_it() -> None:
    """poll and deinit both keep a tally a test can assert against."""
    source = FakeAnalogSource()

    source.poll(15)
    source.deinit()
    source.deinit()

    assert source.poll_calls == 1
    assert source.last_poll_ms == 15
    assert source.deinit_calls == 2
