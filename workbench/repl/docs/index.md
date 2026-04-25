# chumicro-repl

Host-side serial REPL for CircuitPython and MicroPython boards. Runs on your laptop, not on the board.

This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — it helps you talk to boards from your laptop. It is not a library that runs on the microcontroller itself.

## Quick example

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    session.exec("import os")
    sysname = session.call("os.uname")
    print(sysname)
```

Or use the CLI:

```bash
chumicro-repl --address /dev/cu.usbmodem14101
```

Press **Ctrl-X** to quit; **Ctrl-C / Ctrl-D / Ctrl-E** are forwarded to the board, matching the `mpremote repl` keybindings.

## What you get

- **Interactive TUI** — a thin, mpremote-compatible terminal that streams the board's REPL with traceback highlighting.
- **`tail(device, seconds)`** — stream the friendly REPL for a window, fail fast on a traceback, return an `ExitCode`. Used by `chumicro-deploy` orchestration to follow a board after a deploy.
- **`ReplSession`** — programmatic raw-REPL context manager. `exec(code)`, `call(function_name, *args, **kwargs)`, `read_until(pattern, timeout)` for headless test fixtures.
- **`detect_patterns` / `colorize`** — streaming pattern detector + ANSI renderer for CircuitPython `Traceback`, `safe mode`, `Hard fault`, MicroPython `Traceback`, and MicroPython `MPY: soft reboot` banners.
- **`chumicro-repl` CLI** — `--address`, `--devices-file`, `--tail`, `--no-fail-on-traceback`.

## Documentation

- [User Guide](guide.md) — getting started, each surface explained, runtime notes.
- [API Reference](api.md) — full API from the source docstrings.

## Install

```bash
pip install chumicro-repl
```

No bundle registration needed — chumicro-repl is a host tool, not on-device code.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · [PyPI](https://pypi.org/project/chumicro-repl/) · [Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
