"""A keypad wired as rows by columns, read as the same buttons everything else reads."""

import sys

from chumicro_buttons.core import (
    DEFAULT_LONG_PRESS_MS,
    DEFAULT_REPEAT_DELAY_MS,
    DEFAULT_SETTLE_MS,
    Buttons,
)


def _select_matrix_source(row_pins, column_pins, *, columns_to_anodes=True, settle_ms, ticks):
    """Return the matrix scan this runtime can build.

    The MicroPython scan measures its settle window against ``ticks``; the CircuitPython scan
    debounces in firmware and takes none.
    """
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_buttons._adapters.cp import CpKeyMatrixSource
        return CpKeyMatrixSource(
            row_pins, column_pins, columns_to_anodes=columns_to_anodes, settle_ms=settle_ms,
        )
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_buttons._adapters.mp import MpKeyMatrixSource
        return MpKeyMatrixSource(
            row_pins,
            column_pins,
            columns_to_anodes=columns_to_anodes,
            settle_ms=settle_ms,
            ticks=ticks,
        )
    raise RuntimeError(
        "CPython has no GPIO to scan.  Build the matrix with "
        "source=FakeButtonSource(...) from chumicro_buttons.testing and drive it "
        "from your test, or run this on CircuitPython or MicroPython.",
    )


class KeyMatrix(Buttons):
    """A keypad whose keys sit where a row crosses a column, read one key at a time.

    Wiring keys as a grid is what lets twelve of them share seven pins, and every key still
    reads as an ordinary button: ``matrix[5]`` is a :class:`~chumicro_buttons.core.Button` with
    its own ``pressed``, its own edges, and its own long press, repeat, and click counting.
    Keys are numbered row-major, so the key at ``row``, ``column`` is
    ``row * len(column_pins) + column``, and with three columns key 4 is row 1, column 1.

    CircuitPython drives the grid in the firmware's own background scan; MicroPython drives it
    once per ``check(now_ms)``, because a grid has to be scanned a row at a time and column
    interrupts would report keys nobody touched.

    Args:
        row_pins: Runtime pin objects for the rows.
        column_pins: Runtime pin objects for the columns.
        source: Pre-built edge source; overrides the pins.  Tests inject a fake here.
        columns_to_anodes: Which way the matrix's diodes face.  Leave it True when each
            diode's striped end points at a row pin, which is how ready-made keypads are built.
            Guessing wrong is quiet rather than damaging: the diodes block the scan and no key
            ever reads as pressed, so a keypad that reports nothing is the symptom to try it on.
        settle_ms: Debounce window in milliseconds; 0 trusts the signal.
        long_press_ms: Hold time that fires ``just_long_pressed``.  Zero disables it.
        repeat_ms: Interval between repeat fires while held.  Zero disables it.
        repeat_delay_ms: Hold time before repeat starts.
        click_ms: Quiet time that closes a click series.  Zero disables click counting.
        ticks: The clock every duration here is judged by, ``chumicro_timing.ticks`` or
            anything shaped like it.  Required, and it reaches the scan and every key below,
            so the whole keypad measures against one time base.
    """

    def __init__(
        self,
        row_pins: object | None = None,
        column_pins: object | None = None,
        *,
        source: object | None = None,
        columns_to_anodes: bool = True,
        settle_ms: int = DEFAULT_SETTLE_MS,
        long_press_ms: int = DEFAULT_LONG_PRESS_MS,
        repeat_ms: int = 0,
        repeat_delay_ms: int = DEFAULT_REPEAT_DELAY_MS,
        click_ms: int = 0,
        ticks: object,
    ) -> None:
        if source is None:
            if row_pins is None or column_pins is None:
                raise ValueError("KeyMatrix needs either row_pins and column_pins, or source=")
            if len(row_pins) == 0 or len(column_pins) == 0:
                # A grid with no rows or no columns has no keys, and would look like a keypad
                # that never responds.
                raise ValueError("KeyMatrix was given an empty row_pins or column_pins")
            source = _select_matrix_source(
                row_pins,
                column_pins,
                columns_to_anodes=columns_to_anodes,
                settle_ms=settle_ms,
                ticks=ticks,
            )
        super().__init__(
            source=source,
            long_press_ms=long_press_ms,
            repeat_ms=repeat_ms,
            repeat_delay_ms=repeat_delay_ms,
            click_ms=click_ms,
            ticks=ticks,
        )
