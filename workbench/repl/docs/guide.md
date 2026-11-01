# User Guide

`chumicro-repl` connects your laptop's terminal to the REPL of a CircuitPython or MicroPython board over USB serial.  The REPL is the board's `>>>` prompt, where it runs each line of Python as you enter it.  Inside a ChuMicro workspace, `chumicro-workspace repl --device NAME` opens the same session by the board's name.

## Install

```bash
pip install chumicro-repl
```

The install puts a `chumicro-repl` command on your `PATH`.  The board needs only its CircuitPython or MicroPython firmware.

## Open a session

`--address` is the board's serial port.  On macOS, `ls /dev/cu.*` lists the ports.  A board with native USB shows up there as `/dev/cu.usbmodem…`.  On Linux, `ls /dev/ttyACM* /dev/ttyUSB*` lists them.  Run the listing with the board unplugged and again with it plugged in: the new entry is the board.

```bash
chumicro-repl --address /dev/cu.usbmodem1101
```

```text
chumicro-repl line mode: /dev/cu.usbmodem1101
history: /Users/you/.chumicro-repl/history/dev_cu_usbmodem1101/history.txt
  :help     list commands
  :quit     exit
  Ctrl-X    exit
  Ctrl-C    interrupt running program on device
  Ctrl-D    soft-reboot device (at empty prompt)
>>>
```

A terminal session opens in line mode.  The same keys work in both modes:

| Key | Effect |
|---|---|
| Ctrl-X | Ends the session.  The board keeps running. |
| Ctrl-C | Stops the program running on the board and returns to `>>>`. |
| Ctrl-D | At an empty prompt, soft-reboots the board, which restarts its `code.py` or `main.py`. |

Another program with the port open, such as Thonny, Mu, or a `screen` session, keeps the session from starting.  [When a session fails to start](#when-a-session-fails-to-start) shows what `chumicro-repl` prints then.

## Line mode

Line mode edits each line on your laptop and sends it to the board when you press Enter.  The arrow keys move the cursor, up-arrow recalls earlier lines, and Ctrl-R searches them.  The board's answer prints below the line, with tracebacks in red.

A line that starts with `:` runs a command on your laptop and never reaches the board:

| Command | What it does |
|---|---|
| `:help` | Lists every command. |
| `:edit` | Opens `$EDITOR` holding your last 10 lines.  On save and exit, each non-empty line goes to the board in turn.  `vi` opens when `$EDITOR` is unset.  A value with arguments, such as `EDITOR="code -w"`, works. |
| `:save NAME` | Saves your last 10 lines to `~/.chumicro-repl/snippets/NAME.py`. |
| `:load NAME` | Sends a saved snippet to the board line by line. |
| `:snippets` | Lists saved snippet names. |
| `:rescan` | Clears the cached board names, so the next Tab asks the board again.  Use it after an `import`. |
| `:quit` | Ends the session and leaves the board running, like Ctrl-X. |

```text
>>> :rescan
line-mode: completion cache cleared; next Tab will re-query the device
>>> :save bringup-wifi
line-mode: saved 3 line(s) to /Users/you/.chumicro-repl/snippets/bringup-wifi.py
>>> :quit
line-mode: bye
```

History lives in one file per serial port, so lines typed at one board stay out of another board's history.  Port `/dev/cu.usbmodem1101` keeps its history at `~/.chumicro-repl/history/dev_cu_usbmodem1101/history.txt`.

### Tab completion

Tab merges two sources:

- **Python keywords and builtins**, such as `for`, `import`, `print`, and `range`.  These need no board.
- **The board's own names**, from `dir()` on the board.  The first Tab fetches them through the raw REPL.  The session then keeps them cached.  The round trip took between 8 ms and 45 ms on Lolin S2 and Pi Pico W boards under both runtimes.  `:rescan` clears the cache after an `import`.

The round trip makes the board reprint its startup banner.  Line mode reads that banner before redrawing the prompt, so it stays off your screen.  `chumicro_repl.completion.fetch_device_names(port)` runs the same round trip from your own code.

A fresh CircuitPython REPL defines only `__name__` and `__file__` until something is imported.  MicroPython imports a few platform modules at startup, such as `gc`, `os`, and `machine`.  The keyword list covers the names typed most either way.

## Passthrough mode

Passthrough mode sends every key to the board as you press it.  The board does its own line editing.  Paste mode (Ctrl-E on MicroPython) and tools that drive the raw REPL need it.

```bash
chumicro-repl --address /dev/cu.usbmodem1101 --mode passthrough
```

The session prints a dim banner with the port, the baud rate, and the keys, then sends one carriage return so the board reprints its `>>>`:

| Key | Effect |
|---|---|
| Ctrl-C | Sent to the board.  Stops the running program. |
| Ctrl-D | Sent to the board.  Soft-reboots it. |
| Ctrl-E | Sent to the board.  Enters MicroPython's paste mode. |
| Ctrl-X | Ends the session on your laptop.  The board keeps running. |

Every other key goes to the board unchanged.  Arrow keys, backspace, and up-arrow history work through the board's own line editor.  Passthrough mode has no `:` commands and no Tab completion from your laptop.  When the cable drops, passthrough mode tries to reopen the port for up to 60 seconds.  Ctrl-X cancels the wait.

`--mode auto`, the default, picks line mode when input comes from a terminal and passthrough when input is piped, because line mode reads from a terminal.  `--mode line` and `--mode passthrough` pick one outright.

## Watch output with `--tail`

`--tail SECONDS` prints the board's output for that long and exits, in place of an interactive session:

```bash
chumicro-repl --address /dev/cu.usbmodem1101 --tail 30
```

`--tail` sends nothing to the board, so the board keeps running whatever it was running.  The exit status says why the window ended:

| Exit status | Meaning |
|---|---|
| 0 | The time ran out. |
| 1 | A traceback, a CircuitPython safe-mode message, or a CircuitPython hard fault appeared. |
| 2 | Ctrl-C ended the tail. |
| 3 | The board disconnected and stayed gone for 30 seconds. |

`--no-fail-on-traceback` keeps printing for the full time after a traceback and exits 0, to watch a board that crashes and restarts in a loop.  A MicroPython soft-reboot banner prints in dim cyan and never ends the tail.  When the cable drops, the tail waits up to 30 seconds for the board to come back.  That wait adds to the window.

## When a session fails to start

An interactive session that cannot open the board names the failure, prints the steps that fix it, and waits for Enter to retry, up to three attempts.  A held port looks like this:

```text
Attempt 1/3 failed: SerialException
  <the error the serial port raised>

The serial port is held by another process.
  • Close any other tool that may have the port open: Mu, Thonny, the Arduino IDE, screen / minicom, another mpremote, PyCharm or VS Code serial console.
  • On macOS / Linux, `lsof <port>` shows the holding process; kill it or quit the app and retry.
  • If the port was held by a crashed process, unplug + replug the board to force the OS to release it.

Fix the condition above and press Enter to retry…  (2 retries remaining; type 'q' to abort)
```

`q`, `quit`, `abort`, or `exit` stops retrying.  With piped input, the steps print once and the command stops without asking.  `--tail` skips this coaching.

| Kind | What happened | First fix |
|---|---|---|
| `PORT_NOT_FOUND` | No port exists at the address | Plug the board in with a data cable, and check the address with `ls` |
| `PORT_BUSY` | Another program holds the port | Close that program |
| `PORT_PERMISSION_DENIED` | Your user account cannot open the port | On Linux, `sudo usermod -a -G dialout $USER`, then log out and back in |
| `RAW_REPL_UNRESPONSIVE` | The port opened, but the board's REPL did not answer | Tap RESET, or flash CircuitPython or MicroPython |
| `UNKNOWN` | No known pattern matched | Read the error, then retry |

This coaching covers a session that never opened.  A board that drops after the session opened goes through the reconnect waits in passthrough mode and `--tail`.  Line mode ends the session when a write to the dropped port fails.

## Use it from Python

### Follow a board: `tail()`

```python
from chumicro_deploy import Device
from chumicro_repl import tail, ExitCode

device = Device(transport="circuitpython", address="/dev/cu.usbmodem14101")

result = tail(device, seconds=10.0, fail_on_traceback=True)
if result is ExitCode.TRACEBACK_DETECTED:
    raise SystemExit("deploy crashed on the board")
```

`tail()` takes a `chumicro_deploy.Device` or a bare port path.  It returns an `ExitCode`: `OK`, `TRACEBACK_DETECTED`, `INTERRUPTED`, or `DISCONNECTED`, worth 0 to 3 as in the [exit status table](#watch-output-with-tail).  `reconnect_seconds=0.0` turns off the reconnect wait, so a CI job fails at once on a dropped board.  The output stays correct when a multi-byte UTF-8 character splits across two reads.

### Run code on the board: `ReplSession`

`ReplSession` is a context manager.  Entering it stops the program the board is running and switches the board to its raw REPL.  Leaving it returns the board to the normal `>>>` prompt.

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    # Run a block and get back what it printed.
    output = session.exec("import os\nprint(os.listdir('/'))\n")

    # Call a function and get its return value as a Python object.
    session.exec("import gc")
    free_bytes = session.call("gc.mem_free")

    # Wait for the board to print a line that matches a regex.
    captured = session.read_until(r"READY", timeout=5.0)
```

- `exec(code, timeout=10.0)` returns what the code printed.  Code that raises on the board makes `exec` raise `ReplSessionError`, with the board's error text in its `.stderr` attribute.
- `call(function_name, *args, **kwargs)` runs `print(repr(function_name(*args, **kwargs)))` on the board and parses the result with `ast.literal_eval`.  Numbers, strings, bytes, tuples, lists, dicts, sets, booleans, and `None` come back as Python objects.  Any other return value raises `ReplSessionError`.  The function's module must be imported first with `exec`.
- `read_until(pattern, timeout=...)` reads until the regex matches and returns the text up to the match.

`ReplSession` accepts a `chumicro_deploy.Device`, a bare port path, or any object with `.address` and `.baudrate`.

### Retry a failed start: `InteractiveReplSession`

`InteractiveReplSession` wraps `ReplSession` with the startup coaching the command prints:

```python
from chumicro_repl import InteractiveReplSession

with InteractiveReplSession(device, max_attempts=3) as session:
    output = session.exec("print('hello')")
```

`prompt` and `output` take any callable, so a test can feed scripted replies and a GUI can show the steps.  `classify_session_failure(error)` returns the `ReplFailureKind` for an exception, for code that handles failures itself:

```python
from chumicro_repl import ReplFailureKind, ReplSession, ReplSessionError, classify_session_failure

try:
    with ReplSession(device) as session:
        ...
except (OSError, ReplSessionError) as error:
    if classify_session_failure(error) is ReplFailureKind.PORT_BUSY:
        ...  # ask the user to close the other program
```

`coached_session_start(factory)` runs the same retry loop around any function that opens a session.  The `chumicro-repl` command wraps `interactive_line` and `interactive` with it.

### Find tracebacks in text: `detect_patterns` and `colorize`

```python
from chumicro_repl import Theme, colorize, detect_patterns

text = "running\n" + board_output
for match in detect_patterns(text):
    print(match.kind, match.start, match.end)

print(colorize(text), end="")                           # default colors
print(colorize(text, theme=Theme(traceback="32")), end="")  # green tracebacks
```

`chumicro_repl.patterns.StreamingPatternDetector` finds the same patterns in a stream.  It keeps a bounded tail of recent text, so a traceback split across two reads still matches while memory stays flat in a long session.  `tail()` and both interactive modes use it.

### Test without a board

```python
from chumicro_repl import ReplSession
from chumicro_repl.testing import FakeSerialPort, FakeTime

handshake = [b"\r\n", b"raw REPL; CTRL-B to exit\r\n>"]
exec_ok = b"OKhello\n\x04\x04>"
port = FakeSerialPort(read_chunks=[*handshake, exec_ok])

with ReplSession(
    "/dev/cu.fake",
    time=FakeTime(),
    port_factory=lambda *_args, **_kwargs: port,
) as session:
    assert session.exec("print('hello')") == "hello\n"
```

`chumicro_repl.testing` holds three fakes:

- `FakeSerialPort` stands in for `serial.Serial`.  It records writes in `.writes` and returns the scripted `read_chunks` in order.
- `FakeKeyboard` replays scripted keystrokes for `chumicro_repl.tui.run_loop`.
- `FakeTime` is a clock that moves only when told.  `monotonic()` holds still between calls.  `sleep()` advances the clock with no real wait.

## Reference

### Runtime notes

CircuitPython and MicroPython frame the raw REPL the same way.  Both answer Ctrl-A with the raw prompt and send `OK<stdout>\x04<stderr>\x04>` after each command.  They differ in what Ctrl-D prints at the normal `>>>` prompt: MicroPython prints `MPY: soft reboot`, and CircuitPython prints nothing.  `ReplSession` stays in the raw REPL, so only `tail()` and passthrough mode show the difference.

### Highlighted output

| Kind | Runtime | When it appears | Color |
|---|---|---|---|
| Traceback | both | An uncaught exception | Bold red |
| Safe mode | CircuitPython | The supervisor drops into safe mode after repeated crashes | Bold yellow |
| Hard fault | CircuitPython | A crash below the level of Python exceptions | Bold on a red background |
| Soft reboot | MicroPython | Ctrl-D at the `>>>` prompt, or `machine.soft_reset()` | Dim cyan |

### Files on your laptop

| Path | Holds |
|---|---|
| `~/.chumicro-repl/history/<port>/history.txt` | Line-mode history for one port, with `/` and `.` in the port turned into `_` |
| `~/.chumicro-repl/snippets/NAME.py` | A snippet `:save NAME` wrote |

### Examples

- [`tail_after_deploy.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/repl/examples/tail_after_deploy.py) follows a board for ten seconds and exits non-zero on a traceback.
- [`demo_repl_robustness.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/repl/examples/demo_repl_robustness.py) walks a real board through each startup failure and reconnect: a clean session, a wrong address, a held port, a board stuck in code that ignores Ctrl-C, a cable pulled during a tail, and a reconnect cancelled partway.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · \
[PyPI](https://pypi.org/project/chumicro-repl/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
