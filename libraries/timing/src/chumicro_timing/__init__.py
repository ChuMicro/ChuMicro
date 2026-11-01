"""Millisecond timers for a loop that never sleeps.

``ticks_ms``, ``ticks_add``, and ``ticks_diff`` read and compare the clock.  ``Rate`` comes due
every so many milliseconds, and ``Deadline`` expires once.
"""

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
