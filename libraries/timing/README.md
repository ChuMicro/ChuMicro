# chumicro-timing

Cross-runtime millisecond tick helpers and periodic timing utilities for CircuitPython, MicroPython, and CPython.

Provides wraparound-safe `ticks_ms()`, `ticks_diff()`, and `ticks_add()` that work identically across all three runtimes, plus a `Heartbeat` object for periodic task scheduling.

