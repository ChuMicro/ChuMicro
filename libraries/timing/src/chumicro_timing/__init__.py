"""Public exports for the cross-runtime timing package."""

from chumicro_timing.heartbeat import Heartbeat
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Heartbeat",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]
