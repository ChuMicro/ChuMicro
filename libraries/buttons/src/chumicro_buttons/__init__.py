"""Debounced buttons, switches, and key matrices: edges, long presses, repeats, and clicks."""

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
