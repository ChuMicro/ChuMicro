"""Wrap-safe millisecond ticks plus wait value objects (``Deadline`` / ``Rate`` / ``earliest``)."""

import gc

from chumicro_timing.deadline import Deadline, Rate, earliest
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Deadline",
	"Rate",
	"earliest",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]

gc.collect()
