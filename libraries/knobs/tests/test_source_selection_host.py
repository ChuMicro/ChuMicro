"""Host-lane tests for the sources a laptop cannot build.

Picking a source is a per-runtime import, and CPython has no pins to import for.
These assert the refusal and the hint it carries, which is true only off a board:
a real CircuitPython or MicroPython run builds a source here instead of raising,
so each test skips loudly on those runtimes.

Real-hardware coverage of the built sources lives under ``functional_tests/``.
"""

#: Host-lane only: asserts off-target behaviour that a real board contradicts.
__chumicro_host_only__ = True

import sys

from chumicro_knobs import AnalogKnob, Encoder
from chumicro_knobs.analog import _select_analog_source
from chumicro_knobs.encoder import _select_encoder_source
from chumicro_test_harness import raises, skip


def _require_cpython() -> None:
    """Skip loudly when the runtime under test builds a source instead of refusing."""
    runtime_name = sys.implementation.name
    if runtime_name != "cpython":
        skip(f"{runtime_name} has pins, so it builds a source instead of refusing")


def test_selecting_a_quadrature_source_on_cpython_points_at_the_fake() -> None:
    """_select_encoder_source raises RuntimeError naming FakeEncoderSource as the way forward."""
    _require_cpython()

    with raises(RuntimeError, match="FakeEncoderSource"):
        _select_encoder_source(object(), object(), detent_steps=4)


def test_selecting_a_converter_on_cpython_points_at_the_fake() -> None:
    """_select_analog_source raises RuntimeError naming FakeAnalogSource as the way forward."""
    _require_cpython()

    with raises(RuntimeError, match="FakeAnalogSource"):
        _select_analog_source(object())


def test_an_encoder_built_from_pins_refuses_on_cpython() -> None:
    """Passing two pins on a host raises the same RuntimeError from the constructor."""
    _require_cpython()

    with raises(RuntimeError, match="FakeEncoderSource"):
        Encoder(object(), object())


def test_a_knob_built_from_a_pin_refuses_on_cpython() -> None:
    """Passing pin= on a host raises the same RuntimeError from the constructor."""
    _require_cpython()

    with raises(RuntimeError, match="FakeAnalogSource"):
        AnalogKnob(object())
