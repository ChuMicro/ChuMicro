"""Public exports for the cross-runtime timing package."""

from chumicro_timing.heartbeat import Heartbeat
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Heartbeat",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]

import gc as _gc  # noqa: E402, I001 — intentional end-of-module placement.
_gc.collect()
del _gc
