"""Leveled logging for chumicro libraries — runner-friendly, no chumicro deps.

A lightweight subset of stdlib ``logging`` that runs identically on
CircuitPython, MicroPython, and CPython: integer levels, named loggers,
a handler protocol, and a buffered handler that defers I/O to the runner
tick so emission never blocks a hot path.

This package has no chumicro dependencies and **no chumicro library
imports it** — by policy, decoration / observability libraries don't
appear in another library's dependency graph.  Apps wire it in by
passing a logger callable to libraries that accept an optional
``logger=`` parameter, or by attaching their own loggers to runtime
events.

Public API
----------
- Level constants: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``
- ``Logger(name, level, handlers)`` — emits records to attached handlers
- ``StreamHandler(stream, level, formatter)`` — synchronous text output
- ``BufferedHandler(downstream, capacity, level)`` — runner-shaped buffer
- ``default_formatter(level, name, message)`` — ``LEVEL:name:message``
- ``level_name(level)`` — integer to human name
"""

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
