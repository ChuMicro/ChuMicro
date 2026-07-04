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
    # pyright: ignore[reportUnsupportedDunderAll] — GeneratorHandle is
    # PEP-562 lazy via __getattr__ below.
    "IO_READ",
    "IO_WRITE",
    "GeneratorHandle",
    "ReentrantTickError",
    "Runner",
    "TaskHandle",
]


def __getattr__(name: str):
    """Lazy-load ``GeneratorHandle`` on first access (PEP 562).

    ``_generator`` holds the generator-driver classes (~9 KB of source,
    two classes) that only ``Runner.add_generator`` needs.  Keeping this
    re-export lazy means a plain periodic-blink app that never registers
    a generator never loads ``_generator`` — callers that do use
    generators reach ``GeneratorHandle`` through ``add_generator``'s
    return value, or trigger this import by naming it here.
    """
    if name == "GeneratorHandle":
        from chumicro_runner._generator import GeneratorHandle  # noqa: PLC0415

        return GeneratorHandle
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


gc.collect()
