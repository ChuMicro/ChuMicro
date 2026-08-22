"""Debounced buttons, switches, and key matrices that never miss a tap."""

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
