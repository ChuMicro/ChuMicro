"""``Runner``, a scheduler that runs timed jobs, services, and generator tasks from one loop.

Build one ``Runner``, register each job on it once, and call ``now_ms = runner.tick()`` and
``runner.wait(now_ms)`` on every pass of a ``while True:`` loop.  ``GeneratorHandle`` also
imports from here, and loads on first use.

Attributes:
    IO_READ: The bit a service's ``io_interest`` returns to have ``Runner.wait`` wake when
        its socket has data to read.
    IO_WRITE: The bit a service's ``io_interest`` returns to have ``Runner.wait`` wake when
        its socket can send.  OR it with ``IO_READ`` to wait for either.
"""

import gc

from chumicro_runner.core import (
    IO_READ,
    IO_WRITE,
    ReentrantTickError,
    Runner,
    TaskHandle,
)

__all__ = [
    # pyright: ignore[reportUnsupportedDunderAll]: GeneratorHandle is
    # PEP-562 lazy via __getattr__ below.
    "IO_READ",
    "IO_WRITE",
    "GeneratorHandle",
    "ReentrantTickError",
    "Runner",
    "TaskHandle",
]


def __getattr__(name: str):
    # Lazy import: an app with no generator never pulls _generator into RAM.
    if name == "GeneratorHandle":
        from chumicro_runner._generator import GeneratorHandle  # noqa: PLC0415

        return GeneratorHandle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


gc.collect()
