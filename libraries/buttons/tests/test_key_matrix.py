"""Cross-runtime tests for ``KeyMatrix``: a grid of keys numbered row-major.

Plain asserts plus the harness ``raises()`` helper, so they run on CPython (via
pytest) and on MicroPython/CircuitPython (via the lightweight test harness).  The
grid is driven by ``FakeButtonSource`` and timed by ``FakeTicks``, so nothing here
reads a real clock or waits.

A KeyMatrix is a Buttons, so the tick loop, ``handle``, the panel callbacks, and the
overflow flag are covered where Buttons is.  What is checked here is what a grid
adds: how many keys it has, which button each scanned key reaches, and what it
refuses to be built from.
"""

import chumicro_buttons
from chumicro_buttons import Buttons
from chumicro_buttons.matrix import KeyMatrix
from chumicro_buttons.testing import FakeButtonSource
from chumicro_test_harness import raises
from chumicro_timing.testing import FakeTicks

#: The grid these tests describe: four rows of three keys, twelve keys in all.
ROW_COUNT = 4
COLUMN_COUNT = 3


def _grid_source() -> FakeButtonSource:
    """Return a source reporting one key per crossing of the four-by-three grid."""
    return FakeButtonSource(key_count=ROW_COUNT * COLUMN_COUNT)


def _quiet_matrix(source, **options) -> KeyMatrix:
    """Build a KeyMatrix on ``source`` with long press, repeat, and clicks off.

    Each test turns back on only the timing it is about, so an unrelated event
    can never be what a tick reports.
    """
    settings = {"long_press_ms": 0, "repeat_ms": 0, "click_ms": 0}
    settings.update(options)
    return KeyMatrix(source=source, ticks=FakeTicks(), **settings)


def _pressed_keys(matrix) -> list:
    """Return the numbers of every key reading as down, lowest first."""
    down = []
    for key_index in range(len(matrix)):
        if matrix[key_index].pressed:
            down.append(key_index)
    return down


# -- Shape and numbering -----------------------------------------------


def test_a_grid_has_one_key_per_crossing_of_a_row_and_a_column() -> None:
    """Four rows of three columns is twelve keys, each its own Button."""
    matrix = _quiet_matrix(_grid_source())

    assert len(matrix) == ROW_COUNT * COLUMN_COUNT
    assert len(matrix) == 12
    assert len(matrix.keys) == 12
    assert matrix[0] is not matrix[11]


def test_key_four_of_a_four_by_three_grid_is_row_one_column_one() -> None:
    """The worked example of row-major numbering: three columns puts key 4 at row 1, column 1.

    The key number is worked out from the row and column here and the answer is
    checked against the literal 4, so the formula and the documented example have to
    agree, and then key 4 is the button that actually reacts.
    """
    row, column = 1, 1
    key_index = row * COLUMN_COUNT + column
    assert key_index == 4

    source = _grid_source()
    matrix = _quiet_matrix(source)

    source.press(key_index=key_index, at_ms=100)
    assert matrix.check(120) is True

    assert matrix[4].just_pressed is True
    assert matrix[4].held_ms == 20
    assert _pressed_keys(matrix) == [4]


def test_every_scanned_key_reaches_the_button_of_the_same_number() -> None:
    """Key N from the scan lands on matrix[N] and disturbs no other key, across the grid.

    Sweeping all twelve is what catches a grid that arrives transposed or renumbered,
    which a single spot check would miss.
    """
    source = _grid_source()
    matrix = _quiet_matrix(source)

    for key_index in range(ROW_COUNT * COLUMN_COUNT):
        source.press(key_index=key_index, at_ms=0)
        assert matrix.check(0) is True
        assert _pressed_keys(matrix) == [key_index]

        source.release(key_index=key_index, at_ms=1)
        assert matrix.check(1) is True
        assert _pressed_keys(matrix) == []


# -- Construction ------------------------------------------------------


def test_a_grid_with_no_pins_and_no_source_is_refused() -> None:
    """KeyMatrix() names both pin arguments and source= in its refusal."""
    with raises(ValueError, match="row_pins and column_pins, or source="):
        KeyMatrix(ticks=FakeTicks())


def test_a_grid_given_an_empty_side_is_refused() -> None:
    """A grid with no rows or no columns has no keys, so it is refused rather than built."""
    with raises(ValueError, match="empty row_pins or column_pins"):
        KeyMatrix(row_pins=(), column_pins=(), ticks=FakeTicks())

    with raises(ValueError, match="empty row_pins or column_pins"):
        KeyMatrix(row_pins=(object(),), column_pins=(), ticks=FakeTicks())


def test_a_grid_missing_either_half_of_the_wiring_is_refused() -> None:
    """Rows without columns, or columns without rows, is not a grid and raises ValueError."""
    with raises(ValueError, match="row_pins and column_pins, or source="):
        KeyMatrix(row_pins=(object(), object()), ticks=FakeTicks())

    with raises(ValueError, match="row_pins and column_pins, or source="):
        KeyMatrix(column_pins=(object(), object(), object()), ticks=FakeTicks())


def test_a_grid_built_without_a_clock_is_refused() -> None:
    """Omitting ticks= raises TypeError rather than building a grid.

    The clock has no default here, so a caller cannot end up with keys measuring
    against a time base they never chose.
    """
    with raises(TypeError):
        KeyMatrix(source=_grid_source())


def test_the_grid_forwards_its_timings_to_every_key() -> None:
    """long_press_ms, repeat_ms, repeat_delay_ms, and click_ms all reach the keys.

    A short tap earns the click and a separate hold earns the long press and the
    first repeat, so a timing argument dropped on the way through is visible here.
    """
    source = _grid_source()
    matrix = KeyMatrix(
        source=source,
        ticks=FakeTicks(),
        long_press_ms=300,
        repeat_ms=100,
        repeat_delay_ms=300,
        click_ms=200,
    )

    source.press(key_index=7, at_ms=0)
    matrix.check(0)
    source.release(key_index=7, at_ms=50)
    matrix.check(50)

    assert matrix.check(250) is True
    assert matrix[7].just_clicked is True
    assert matrix[7].click_count == 1

    source.press(key_index=2, at_ms=300)
    matrix.check(300)

    assert matrix.check(600) is True
    assert matrix[2].just_long_pressed is True
    assert matrix[2].just_repeated is True


def test_the_grid_is_reached_through_its_own_module() -> None:
    """``chumicro_buttons.matrix`` publishes KeyMatrix, and a KeyMatrix is a Buttons.

    Subclassing Buttons is where the tick loop, handle, and the panel callbacks come
    from, which is why this file does not check them again.
    """
    from chumicro_buttons import matrix

    assert matrix.KeyMatrix is KeyMatrix
    assert issubclass(KeyMatrix, Buttons)


def test_the_package_does_not_carry_the_grid_itself() -> None:
    """KeyMatrix is absent from the package's __all__ and from the package namespace.

    A package-level import would put the scan on every board that installs the
    library, including the ones wired for discrete buttons only, so the grid is
    reached through its own module instead.
    """
    assert "KeyMatrix" not in chumicro_buttons.__all__
    assert hasattr(chumicro_buttons, "KeyMatrix") is False
    assert "Button" in chumicro_buttons.__all__
    assert "Buttons" in chumicro_buttons.__all__
