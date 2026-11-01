"""``KeyMatrix``: a keypad wired as a grid of rows and columns, read as one ``Button`` per key.

Import it from ``chumicro_buttons.matrix``.  ``import chumicro_buttons`` leaves this module
unloaded, so a board with only separate buttons spends no RAM on it.
"""

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
    """A keypad wired as a grid of rows and columns, read as one ``Button`` per key.

    A grid lets twelve keys share seven pins, and each key is still an ordinary ``Button``:
    ``matrix[5]`` has its own ``pressed``, its own edges, and its own long press, repeat, and
    click counting.  Keys are numbered across each row in turn, so the key at ``row``,
    ``column`` is ``row * len(column_pins) + column``.  With three columns, key 4 is row 1,
    column 1.  ``check``, ``handle``, the callbacks, and indexing work as on ``Buttons``.

    CircuitPython scans the grid in the background.  MicroPython scans it once per
    ``check(now_ms)``, because a grid is driven one row at a time.  On MicroPython, a loop
    that stalls for long stretches can miss a very short tap.

    Args:
        row_pins: The pins wired to the keypad's rows.
        column_pins: The pins wired to the keypad's columns.
        ticks: The clock every duration is measured on, shared by the scan and every key, as
            for ``Button``.
        source: A ready-made edge source, used in place of the pins.  Tests pass
            ``FakeButtonSource`` from ``chumicro_buttons.testing``.
        columns_to_anodes: Which way the keypad's diodes face, for a keypad that has them.
            Leave it True when each diode's striped end points at a row pin.  A wrong guess
            damages nothing: the diodes block the scan and no key ever reads as pressed,
            which is the sign to flip it.
        settle_ms: Debounce window in milliseconds, as for ``Button``.
        long_press_ms: Hold time in milliseconds before a key's ``just_long_pressed`` fires.
            0 turns long press off.
        repeat_ms: Milliseconds between a held key's ``just_repeated`` fires.  0 turns
            auto-repeat off.
        repeat_delay_ms: Hold time in milliseconds before auto-repeat starts.
        click_ms: Quiet time in milliseconds that ends a key's click series.  0 turns click
            counting off.

    Raises:
        ValueError: Neither both pin lists nor ``source`` was given, or a pin list is empty.
        RuntimeError: Pins were given on CPython, which has no pins to scan, or on a
            CircuitPython build without the ``keypad`` module.
    """

    def __init__(
        self,
        row_pins: object | None = None,
        column_pins: object | None = None,
        *,
        ticks: object,
        source: object | None = None,
        columns_to_anodes: bool = True,
        settle_ms: int = DEFAULT_SETTLE_MS,
        long_press_ms: int = DEFAULT_LONG_PRESS_MS,
        repeat_ms: int = 0,
        repeat_delay_ms: int = DEFAULT_REPEAT_DELAY_MS,
        click_ms: int = 0,
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
