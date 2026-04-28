"""Logging buffered through the runner.

A ``BufferedHandler`` between the logger and the stream decouples log
emission from the hot path.  ``check`` / ``handle`` plug into a
runner; records pile up in the buffer between ticks and flush in
batches when the runner reaches the buffered handler.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    flushed 3 records this tick
    INFO:sensor:reading 1
    INFO:sensor:reading 2
    INFO:sensor:reading 3
"""

from chumicro_logging import (
    DEBUG,
    BufferedHandler,
    Logger,
    StreamHandler,
)

stream = StreamHandler()
buffered = BufferedHandler(downstream=stream, capacity=16)
logger = Logger("sensor", level=DEBUG, handlers=[buffered])

# Hot loop emits cheaply — no I/O until handle() drains the buffer.
for index in range(1, 4):
    logger.info(f"reading {index}")

# Runner cadence — once per tick.
if buffered.check(now_ms=0):
    flushed = buffered.handle(now_ms=0)
    print(f"flushed {flushed} records this tick")
