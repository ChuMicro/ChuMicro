"""Leveled logging for chumicro libraries, with no chumicro dependencies.

A lightweight subset of the standard library ``logging`` that runs the same on
CircuitPython, MicroPython, and CPython: integer levels, named loggers, a
handler protocol, and a buffered handler that defers I/O to the runner tick so
emission never blocks a hot path.
"""

import gc

from chumicro_logging.core import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    WARNING,
    BufferedHandler,
    Logger,
    StreamHandler,
    default_formatter,
    level_name,
)

__all__ = [
    "BufferedHandler",
    "CRITICAL",
    "DEBUG",
    "ERROR",
    "INFO",
    "Logger",
    "StreamHandler",
    "WARNING",
    "default_formatter",
    "level_name",
]

gc.collect()
