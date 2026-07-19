# chumicro-logging

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Buffer log lines off the hot path so logging never stalls your control loop.**

Stdlib-compatible level constants (`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`) and per-logger thresholds give you a familiar shape for code that already speaks `logging`.  The runner-friendly piece lives in `BufferedHandler`, which buffers raw records on the hot path and defers both formatting and I/O to drain time on the runner tick.

<br clear="left">

**Status: parked.**  chumicro-logging works as documented and stays published, but it is not under active development and no other ChuMicro library integrates with it.  Adopt it as a standalone buffered logger, or skip it.

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_logging

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_logging

# CPython
pip install chumicro-logging
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_logging import INFO, Logger, StreamHandler

logger = Logger("boot", level=INFO, handlers=[StreamHandler()])
logger.info("hello")        # -> stdout: INFO:boot:hello
logger.debug("invisible")   # below threshold; dropped silently
```

For non-blocking emission inside a runner tick, wrap the stream handler:

```python
from chumicro_logging import BufferedHandler, DEBUG, Logger, StreamHandler

stream = StreamHandler()
buffered = BufferedHandler(downstream=stream, capacity=32)
logger = Logger("sensor", level=DEBUG, handlers=[buffered])

# hot path, no I/O
logger.info("reading 1")

# runner tick: drains the buffer
if buffered.check(now_ms):
    buffered.handle(now_ms)
```

## What's included

| Symbol | Purpose |
|---|---|
| `Logger(name, level, handlers)` | Named logger; emits records to attached handlers. |
| `StreamHandler(stream, level, formatter)` | Synchronous text output. Default stream is `sys.stdout`. |
| `BufferedHandler(downstream, capacity, level)` | Runner-shaped buffer; `check`/`handle` drain to downstream. |
| `default_formatter(level, name, message)` | Formats as `LEVEL:name:message`. |
| `level_name(level)` | Integer level → human name (`"INFO"`, `"LEVEL15"`). |
| `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` | Stdlib-compatible level integers. |

Test helpers in `chumicro_logging.testing`:

| Symbol | Purpose |
|---|---|
| `RecordingHandler` | Captures records in a list for assertions. |
| `FailingHandler` | Raises on every `emit` to exercise error paths. |

## Where this fits

A leaf library: no upstream ChuMicro deps, and by policy no other ChuMicro library imports `chumicro-logging` (decoration / observability libraries stay out of each other's dependency graphs).  Apps build a `Logger`, attach handlers, and call its level methods (`debug`, `info`, `warning`, `error`, `critical`) directly, or hand the logger to their own modules.

## Platform support

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`examples/stream_handler.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/logging/examples/stream_handler.py) | Logger + StreamHandler at INFO threshold. |
| [`examples/buffered_runner.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/logging/examples/buffered_runner.py) | BufferedHandler decoupling a hot loop from I/O via runner-shaped check / handle. |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/logging/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/logging/experimental/)**

## Find this library

- **PyPI:** [chumicro-logging](https://pypi.org/project/chumicro-logging/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_logging) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_logging)
- **Source:** [libraries/logging](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/logging)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
