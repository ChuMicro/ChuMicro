# chumicro-screens

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Display flushing that never stalls your loop.**

Draw the frame, call `show()`, and the flush crosses the bus one bounded transfer per tick, with a frame-rate floor so redraws don't monopolize the loop.  Panel drivers are duck-typed; hardware drivers land per controller as they pass the project bench.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_screens

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_screens

# CPython
pip install chumicro-screens
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

```python
from chumicro_screens import ScreenService
from chumicro_timing import ticks_ms

class ConsolePanel:
    """Pretend driver: one print stands in for one bus transfer."""
    def __init__(self):
        self.message = ""
    def flush(self):
        print("transfer 1:", self.message[:8])
        yield
        print("transfer 2:", self.message[8:])

panel = ConsolePanel()
screen = ScreenService(panel, refresh_interval_ms=50)
panel.message = "hello screens"
screen.show()

for loop_pass in range(4):
    now_ms = ticks_ms()
    if screen.check(now_ms):
        screen.handle(now_ms)    # one transfer per pass; the loop stays live
# prints "transfer 1: hello sc", then "transfer 2: reens" on the next pass
```

## What's included

### Core

| Symbol | Description |
|---|---|
| `ScreenService(panel, refresh_interval_ms=50, ticks=None)` | Runner-shaped pacer that advances a panel's flush one bus transfer per tick |
| `ScreenService.show()` | Mark the drawn frame ready; the next due tick starts its flush |
| `ScreenService.check(now_ms)` / `handle(now_ms)` | The runner contract: due-test, then one-transfer advance |
| `ScreenService.next_deadline(now_ms)` | Lets `Runner.wait()` sleep until the next flush is due |

### Panel protocol

| Symbol | Description |
|---|---|
| `panel.flush()` | Duck-typed: returns an iterator; each advance performs one bounded bus transfer (a page, strip, or window) |

### Testing

| Symbol | Description |
|---|---|
| `chumicro_screens.testing.FakePanel` | Counts flush starts, transfers, and completions, and can inject a bus fault mid-frame |

## Where this fits

Depends on [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for tick arithmetic.  Apps typically register the service with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), though a hand-written loop calling `check()` / `handle()` works the same.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

### Drivers ship after bench validation

The package currently provides the pacing service and the panel protocol; per-controller hardware drivers are added as each passes validation on real boards.  Writing your own panel is one method: `flush()` returning an iterator that does one bounded bus transfer per advance.

## Examples

| Example | What it shows |
|---|---|
| [`paced_flush.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/screens/examples/paced_flush.py) | A three-row frame flushing one row per loop pass on CPython, no hardware needed |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/screens/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/screens/experimental/)**

## Find this library

- **PyPI:** [chumicro-screens](https://pypi.org/project/chumicro-screens/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_screens) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_screens)
- **Source:** [libraries/screens](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/screens)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
