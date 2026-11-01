---
title: "chumicro-repl: serial REPL for CircuitPython and MicroPython boards"
---

# chumicro-repl

**Type Python at a CircuitPython or MicroPython board from your laptop's terminal, or watch what the board prints.**

`chumicro-repl` opens a board's REPL, the `>>>` prompt where the board runs each line of Python as you enter it.  It edits each line on your laptop before sending it, with up-arrow history kept per board and Tab completion against the names the board has defined.  Tracebacks print in red.

Inside a ChuMicro workspace, `chumicro-workspace repl --device NAME` opens the same session by the board's name in `devices.yml`.  `chumicro-repl` takes a serial port instead, so it works with no workspace at all.  Its Python API serves scripts and test fixtures.

## Three commands

`--address` is the board's serial port.  On macOS, `ls /dev/cu.usbmodem*` lists the ports.  On Linux, `ls /dev/ttyACM*` lists them.

```bash
# Open the board's >>> prompt.
chumicro-repl --address /dev/cu.usbmodem1101

# Send every key to the board as it is pressed, for paste mode and raw-REPL tools.
chumicro-repl --address /dev/cu.usbmodem1101 --mode passthrough

# Print 10 seconds of the board's output, then exit.  Exits 1 on a traceback.
chumicro-repl --address /dev/cu.usbmodem1101 --tail 10
```

In a session, Ctrl-X ends the session and leaves the board running.  Ctrl-C stops the program running on the board.  Ctrl-D at an empty prompt soft-reboots the board.  In line mode, a line that starts with `:` runs a command on your laptop: `:help` lists them, `:edit` opens your recent lines in `$EDITOR`, and `:save` and `:load` keep snippets.

## From Python

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    session.exec("import gc")
    free_bytes = session.call("gc.mem_free")
    print(free_bytes)
```

`tail(device, seconds)` follows a board after a deploy and returns `ExitCode.TRACEBACK_DETECTED` when the board crashes.  `InteractiveReplSession` adds a retry loop with fix steps when a session fails to start.

## Documentation

- [User Guide](guide.md): line mode, passthrough mode, `--tail`, startup failures, then the Python API and reference tables.
- [API Reference](api.md): every public name, generated from the source docstrings.

## Install

```bash
pip install chumicro-repl
```

`chumicro-repl` runs on your laptop, so the board needs no install of its own beyond CircuitPython or MicroPython firmware.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · \
[PyPI](https://pypi.org/project/chumicro-repl/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
