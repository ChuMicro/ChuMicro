"""Public exports for the chumicro-runner package."""

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
    # Lazy PEP 562 import: an app that never registers a generator never
    # loads _generator (the generator-driver classes) into RAM.
    if name == "GeneratorHandle":
        from chumicro_runner._generator import GeneratorHandle  # noqa: PLC0415

        return GeneratorHandle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


gc.collect()
