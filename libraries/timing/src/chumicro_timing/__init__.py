"""Wrap-safe millisecond ticks plus wait value objects (``Deadline`` / ``Rate``)."""

import gc

from chumicro_timing.deadline import Deadline, Rate
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Deadline",
	"Rate",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]

gc.collect()
