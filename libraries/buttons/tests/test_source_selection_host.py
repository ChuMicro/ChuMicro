"""Host-lane tests for the edge sources a laptop cannot build.

Picking an edge source is a per-runtime import, and CPython has no GPIO to
import for.  Discrete pins and a row-by-column grid pick separately and refuse
separately, so both refusals are checked.  This is true only off a board: a real
CircuitPython or MicroPython run builds a source here instead of raising, so each
test skips loudly on those runtimes.

Real-hardware coverage of the built sources lives under ``functional_tests/``.
"""

#: Host-lane only: asserts off-target behaviour that a real board contradicts.
__chumicro_host_only__ = True

import sys

from chumicro_buttons import Button, Buttons
from chumicro_buttons.core import _select_source
from chumicro_buttons.matrix import KeyMatrix, _select_matrix_source
from chumicro_test_harness import raises, skip


def _require_cpython() -> None:
    """Skip loudly when the runtime under test builds a source instead of refusing."""
    runtime_name = sys.implementation.name
    if runtime_name != "cpython":
        skip(f"{runtime_name} has GPIO, so it builds an edge source instead of refusing")


def test_selecting_a_source_on_cpython_points_at_fake_button_source() -> None:
    """_select_source raises RuntimeError naming FakeButtonSource as the way forward."""
    _require_cpython()

    with raises(RuntimeError, match="FakeButtonSource"):
        _select_source((object(),), active_low=True, settle_ms=20)


def test_a_button_built_from_a_pin_refuses_on_cpython() -> None:
    """Passing pin= on a host raises the same RuntimeError from the constructor."""
    _require_cpython()

    with raises(RuntimeError, match="FakeButtonSource"):
        Button(object())


def test_a_panel_built_from_pins_refuses_on_cpython() -> None:
    """Passing pins= on a host raises the same RuntimeError from the constructor."""
    _require_cpython()

    with raises(RuntimeError, match="FakeButtonSource"):
        Buttons((object(), object()))


def test_selecting_a_matrix_scan_on_cpython_points_at_fake_button_source() -> None:
    """_select_matrix_source raises RuntimeError naming FakeButtonSource as the way forward."""
    _require_cpython()

    with raises(RuntimeError, match="FakeButtonSource"):
        _select_matrix_source(
            (object(), object()),
            (object(), object()),
            columns_to_anodes=True,
            settle_ms=20,
        )


def test_a_grid_built_from_row_and_column_pins_refuses_on_cpython() -> None:
    """A grid given both halves of its wiring reaches the scan picker and is refused there.

    Both pin arguments present is what takes the constructor past its own ValueError
    and into the per-runtime import, so this is the path the ValueError tests cannot
    reach.
    """
    _require_cpython()

    with raises(RuntimeError, match="FakeButtonSource"):
        KeyMatrix((object(), object()), (object(), object(), object()))


def test_the_grid_forwards_its_diode_orientation_to_the_scan_picker() -> None:
    """Both settings of columns_to_anodes reach the picker and end in the host refusal.

    The picker takes the orientation as a keyword with no default of its own, so a
    constructor that dropped it would raise TypeError here rather than the
    RuntimeError a host is supposed to get.
    """
    _require_cpython()

    with raises(RuntimeError, match="FakeButtonSource"):
        KeyMatrix((object(),), (object(),), columns_to_anodes=True)

    with raises(RuntimeError, match="FakeButtonSource"):
        KeyMatrix((object(),), (object(),), columns_to_anodes=False)
