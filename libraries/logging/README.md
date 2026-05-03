# chumicro-logging

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Levelled logging for chumicro libraries — runner-friendly, no chumicro deps.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-logging

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

# hot path — no I/O
logger.info("reading 1")

# runner tick — drains the buffer
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
| `get_logger(name, level, handlers)` | Convenience constructor. No global registry. |
| `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` | Stdlib-compatible level integers. |

Test helpers in `chumicro_logging.testing`:

| Symbol | Purpose |
|---|---|
| `RecordingHandler` | Captures records in a list for assertions. |
| `FailingHandler` | Raises on every `emit` — exercises error paths. |

## Platform support

Pure-Python; runs identically on CPython, MicroPython, and CircuitPython.  No chumicro dependencies and **no other chumicro library imports it** ([Decision 0042](../../plans/decisions/0042-library-dependency-policy.md) — the "decoration / observability" rule).  Apps wire logging in by passing the logger to libraries that accept an optional `logger=` parameter.

## Examples

| Example | What it shows |
|---|---|
| [`examples/quickstart.py`](examples/quickstart.py) | Logger + StreamHandler at INFO threshold. |
| [`examples/buffered_runner.py`](examples/buffered_runner.py) | BufferedHandler decoupling a hot loop from I/O via runner-shaped check / handle. |

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries logging
python scripts/run.py test-libraries-functional --library logging
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/logging/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/logging/experimental/)**

## Find this library

- **PyPI:** [chumicro-logging](https://pypi.org/project/chumicro-logging/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_logging) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_logging)
- **Source:** [libraries/logging](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/logging)
