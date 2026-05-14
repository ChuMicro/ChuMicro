# chumicro-repl

**Host-side serial REPL for CircuitPython and MicroPython boards.**

Interactive TUI with traceback highlighting + a programmatic `ReplSession` for headless test fixtures.  Runs on your laptop — not on the board.

## Quick example

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    session.exec("import os")
    sysname = session.call("os.uname")
    print(sysname)
```

Or use the CLI — point it at a serial port path:

```bash
chumicro-repl --address /dev/cu.usbmodem14101
```

Press **Ctrl-X** to quit; **Ctrl-C / Ctrl-D / Ctrl-E** are forwarded to the board, matching the `mpremote repl` keybindings. On connect, `chumicro-repl` prints a dim banner with the connection details and key hints, and nudges the friendly REPL to reprint its `>>>` so you don't sit at a blank screen.

## What you get

- **Interactive TUI** — a thin, mpremote-compatible terminal that streams the board's REPL with traceback highlighting, a startup banner that names the connection + keybindings, and auto-reconnect when the cable drops mid-session.
- **`InteractiveReplSession`** — sibling of `chumicro_deploy.InteractiveDeployer`.  Wraps `ReplSession` with classification + retry + coaching for session-start failures.
- **`tail(device, seconds)`** — stream the friendly REPL for a window, fail fast on a traceback, return an `ExitCode`.  Useful as a post-deploy follow-up step.
- **`ReplSession`** — programmatic raw-REPL context manager. `exec(code)`, `call(function_name, *args, **kwargs)`, `read_until(pattern, timeout)` for headless test fixtures.
- **`detect_patterns` / `colorize`** — streaming pattern detector + ANSI renderer for CircuitPython `Traceback`, `safe mode`, `Hard fault`, MicroPython `Traceback`, and MicroPython `MPY: soft reboot` banners.
- **`chumicro-repl` CLI** — `--address`, `--baudrate`, `--tail`, `--no-fail-on-traceback`, `--mode {line,passthrough}`.

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

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · \
[PyPI](https://pypi.org/project/chumicro-repl/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
