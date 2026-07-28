# chumicro-repl

**Host-side serial REPL for CircuitPython and MicroPython boards.**

Four surfaces: a line-mode editor, a byte-passthrough TUI, a one-shot `tail()` follow mode, and a programmatic `ReplSession` for headless test fixtures.  Runs on your laptop, not on the board.

## Quick example

Point the CLI at a serial port path:

```bash
chumicro-repl --address /dev/cu.usbmodem14101
```

On a terminal that opens **line mode**, a host-side line editor that reads a complete line before shipping it to the device.  Up-arrow recalls history from earlier sessions on the same board, Ctrl-R searches back through it, and Tab completes Python keywords plus whatever the board already has in scope.  Lines starting with `:` run locally instead of going to the device: `:help` lists them, `:edit` hands the recent buffer to `$EDITOR`, `:save` and `:load` keep snippets around.  `:quit`, Ctrl-D, or Ctrl-C at an empty prompt exits without rebooting the board.

Need byte-exact forwarding for paste mode or raw-REPL framing?  Add `--mode passthrough`.  Keystrokes then go straight to the device, Ctrl-C / Ctrl-D / Ctrl-E are forwarded to match the `mpremote repl` keybindings, and Ctrl-X quits the TUI locally.  Either way, `chumicro-repl` prints a dim banner on connect with the connection details and key hints, and nudges the friendly REPL to reprint its `>>>` so you don't sit at a blank screen.

From Python:

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    session.exec("import os")
    sysname = session.call("os.uname")
    print(sysname)
```

## What you get

- **Line mode**, the default on a terminal: a host-side line editor with cursor edit, Ctrl-R reverse search, and history that persists per device under `~/.chumicro-repl/history/`, so a session on one board doesn't pollute another.  `interactive_line(device)` opens it from Python.
- **`:commands` inside line mode**: `:help`, `:edit`, `:save`, `:load`, `:snippets`, `:rescan`, `:quit`.  The table is `BUILTIN_COMMANDS`, and a handler receives a `LineModeContext`, so you can register your own.
- **Tab completion** against Python keywords and builtins (no device round-trip) merged with the board's own `dir()`, fetched on first Tab and cached for the session.  `fetch_device_names(port)` drives that round-trip on its own, `build_default_completer()` assembles the completer, and `CompletionCache` is what `:rescan` clears.
- **Passthrough mode**: a thin, mpremote-compatible terminal that streams the board's REPL byte for byte, with traceback highlighting, a startup banner naming the connection and keybindings, and auto-reconnect when the cable drops mid-session.  `interactive(device)` opens it from Python.
- **`tail(device, seconds)`**: stream the friendly REPL for a window, fail fast on a traceback, return an `ExitCode`.  Useful as a post-deploy follow-up step.
- **`ReplSession`**: programmatic raw-REPL context manager.  `exec(code)`, `call(function_name, *args, **kwargs)`, `read_until(pattern, timeout)` for headless test fixtures.
- **`InteractiveReplSession`**: sibling of `chumicro_deploy.RecoveringDeployer`.  Wraps `ReplSession` with classification, retry, and coaching for session-start failures.
- **`detect_patterns` / `colorize`**: streaming pattern detector and ANSI renderer for CircuitPython `Traceback`, `safe mode`, `Hard fault`, MicroPython `Traceback`, and MicroPython `MPY: soft reboot` banners.
- **`chumicro-repl` CLI**: `--address`, `--baudrate`, `--tail`, `--no-fail-on-traceback`, and `--mode {auto,line,passthrough}` (`auto` is the default and picks line mode on a terminal, passthrough when stdin is piped).

## Documentation

- [User Guide](guide.md), for getting started, each surface explained, and runtime notes.
- [API Reference](api.md), the full API from the source docstrings.

## Install

```bash
pip install chumicro-repl
```

No bundle registration needed.  chumicro-repl is a host tool, not on-device code.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · \
[PyPI](https://pypi.org/project/chumicro-repl/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
