"""Re-exports the millisecond-tick helpers and ``Heartbeat`` as the public surface."""

import gc

from chumicro_timing.heartbeat import Heartbeat
from chumicro_timing.ticks import ticks_add, ticks_diff, ticks_ms

__all__ = [
	"Heartbeat",
	"ticks_add",
	"ticks_diff",
	"ticks_ms",
]

# Reclaims import-time scratch so the package settles into its steady-state footprint.
gc.collect()
