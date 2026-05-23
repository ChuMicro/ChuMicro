"""Public exports for the chumicro-runner package."""

from chumicro_runner.core import (
    Runner,
    TaskHandle,
)

__all__ = [
    "Runner",
    "TaskHandle",
]

# Defragment compile-time scratch at the end of the package import so
# downstream library imports land in a cleaner heap.  See
# chumicro_mqtt/__init__.py docstring.
import gc as _gc
_gc.collect()
del _gc
