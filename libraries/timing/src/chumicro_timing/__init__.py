"""Public exports for the cross-runtime timing package."""

from .heartbeat import Heartbeat
from .ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Heartbeat",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]
