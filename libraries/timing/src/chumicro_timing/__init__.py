"""Public exports for the cross-runtime timing package."""

from chumicro_timing.heartbeat import Heartbeat
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Heartbeat",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]

# Defragment compile-time scratch at the end of the package import so
# downstream library imports land in a cleaner heap.  See
# chumicro_mqtt/__init__.py docstring.
import gc as _gc
_gc.collect()
del _gc
