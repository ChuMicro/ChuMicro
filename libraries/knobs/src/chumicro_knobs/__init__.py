"""Rotary encoders and analog knobs, read as a position that holds still."""

import gc

from chumicro_knobs.analog import (
    DEFAULT_DEADBAND,
    DEFAULT_STEPS,
    RAW_RANGE,
    AnalogKnob,
)
from chumicro_knobs.encoder import DEFAULT_DETENT_STEPS, Encoder

__all__ = [
    "DEFAULT_DEADBAND",
    "DEFAULT_DETENT_STEPS",
    "DEFAULT_STEPS",
    "RAW_RANGE",
    "AnalogKnob",
    "Encoder",
]

gc.collect()
