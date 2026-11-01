"""Debounced buttons and switches, with long press, auto-repeat, and click counting.

``Button`` reads one button and ``Buttons`` reads several.  ``KeyMatrix``, for a keypad
wired as rows and columns, imports from ``chumicro_buttons.matrix``.
"""

import gc

from chumicro_buttons.core import (
    DEFAULT_LONG_PRESS_MS,
    DEFAULT_REPEAT_DELAY_MS,
    DEFAULT_SETTLE_MS,
    Button,
    Buttons,
)

__all__ = [
    "DEFAULT_LONG_PRESS_MS",
    "DEFAULT_REPEAT_DELAY_MS",
    "DEFAULT_SETTLE_MS",
    "Button",
    "Buttons",
]

gc.collect()
