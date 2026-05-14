# User Guide

## Overview

`chumicro-logging` is a small leveled logger that runs identically on
CircuitPython, MicroPython, and CPython.  It exposes the familiar
stdlib-`logging` shape (level integers, named loggers, attached
handlers) without depending on any other chumicro library, and adds a
runner-shaped `BufferedHandler` so log emission can be deferred off
the hot tick path.

The two key types are `Logger` (named, level-thresholded, owns a list
of handlers) and `StreamHandler` (synchronous text output to a
writable stream).  `BufferedHandler` is a runner-shaped front-end that
batches records and flushes them on `handle(now_ms)`.

No other ChuMicro library imports this one — apps wire logging in by passing a logger callable to the optional `logger=` parameter on libraries that accept one.

## Getting started

```python
from chumicro_logging import INFO, Logger, StreamHandler

logger = Logger("boot", level=INFO, handlers=[StreamHandler()])

logger.info("up")          # -> stdout: INFO:boot:up
logger.warning("careful")  # -> stdout: WARNING:boot:careful
logger.debug("invisible")  # below threshold; dropped silently
```

`Logger` is *not* registered globally.  Every call to `Logger("foo")`
returns a fresh instance — the caller owns and stores the reference.
This avoids import-order surprises and keeps the library stateless.

Switch threshold at runtime by assigning to `logger.level`:

```python
from chumicro_logging import DEBUG

logger.level = DEBUG
logger.debug("now visible")
```

Handler exceptions never escape the logger — they increment
`logger.handler_errors` and are otherwise swallowed.  A misbehaving
handler can never crash the application that uses it.

## Runner pattern

The hot path on a microcontroller cannot afford to write to the
serial console synchronously.  `BufferedHandler` decouples emission
from I/O: `emit` appends to a bounded buffer and returns immediately;
`check(now_ms)` returns `True` when records are pending; `handle(now_ms)`
drains the buffer to the downstream handler.

```python
from chumicro_logging import BufferedHandler, DEBUG, Logger, StreamHandler

stream = StreamHandler()
buffered = BufferedHandler(downstream=stream, capacity=32)
logger = Logger("sensor", level=DEBUG, handlers=[buffered])

# Hot loop — cheap, no I/O.
for index in range(100):
    logger.info(f"sample {index}")

# Runner tick — drains the buffer.
if buffered.check(now_ms):
    buffered.handle(now_ms)
```

When the rate exceeds the flush cadence and the buffer fills,
**the oldest record is dropped** and `buffered.dropped` is
incremented.  Newest data wins on the assumption the operator wants
to see *recent* activity rather than ancient backlog.

Wiring into a `chumicro-runner.Runner` is direct — `BufferedHandler`
already implements the `check(now_ms) -> bool` + `handle(now_ms)`
contract.

## Memory notes

`BufferedHandler` keeps a bounded buffer of `(level, name, message)`
tuples up to `capacity` deep.  At the default capacity of 32, expect
roughly `32 × (sizeof tuple + sizeof message)` bytes resident.  Tune
`capacity` to your environment — small enough to bound the memory
budget, large enough to absorb the worst-case rate between runner
ticks.

`StreamHandler` allocates a fresh string per record (the formatter
output) and immediately writes it; it keeps no internal buffer.  On
embedded runtimes the per-record allocation is the dominant cost —
prefer `BufferedHandler` in front of it for hot paths.

`Logger` itself stores a reference to each handler in a list and an
integer error counter.  The handler list snapshot returned by
`logger.handlers` is a tuple, so iterating it does not allocate.

## Platform notes

Runs identically on CPython, MicroPython, and CircuitPython.  No
runtime-specific code paths and no `sys.implementation` checks — the
library uses only `sys` and built-in types.

`StreamHandler`'s default stream is `sys.stdout`, which on
microcontrollers writes to the serial console; on CPython any
file-like object works.  The handler calls `stream.flush()` after
every write when the stream exposes it; streams without `flush` (some
custom test doubles) are also fine.

## Examples

| Example | What it shows |
|---|---|
| [`examples/stream_handler.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/logging/examples/stream_handler.py) | `Logger` + `StreamHandler` at INFO threshold, level switching at runtime. |
| [`examples/buffered_runner.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/logging/examples/buffered_runner.py) | `BufferedHandler` decoupling a hot loop from I/O via the runner-shaped `check` / `handle` contract. |

Both examples run on every supported runtime; neither requires
hardware.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/logging) · \
[PyPI](https://pypi.org/project/chumicro-logging/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
