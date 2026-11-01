# chumicro-repl

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Type Python at a CircuitPython or MicroPython board from your laptop's terminal, or watch what the board prints.**

`chumicro-repl` opens a board's REPL, the `>>>` prompt where the board runs each line of Python as you enter it.  It edits each line on your laptop before sending it, with up-arrow history kept per board and Tab completion against the names the board has defined.  Tracebacks print in red.  `--tail` prints the board's output for a set time and exits 1 on a traceback, which suits a script that checks a fresh deploy.

Inside a ChuMicro workspace, `chumicro-workspace repl --device NAME` opens the same session by the board's name in `devices.yml`.  `chumicro-repl` takes a serial port instead, so it works with no workspace at all.  Its Python API serves scripts and test fixtures.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family, small focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop, not on the board.

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

In a session, Ctrl-X ends the session and leaves the board running.  Ctrl-C stops the program running on the board.  Ctrl-D at an empty prompt soft-reboots the board.  Another program with the port open, such as Thonny, Mu, or a `screen` session, keeps the session from starting.  `chumicro-repl` then prints the steps that free the port.

The [user guide](https://chumicro.com/ChuMicro/repl/stable/guide/) covers both modes, `--tail`, and the Python API.

## Install

```bash
pip install chumicro-repl
```

`pyserial` and `prompt_toolkit` install with it.  The board needs only its CircuitPython or MicroPython firmware.  Passthrough mode needs the POSIX `termios` module, which native Windows lacks.  WSL2 works.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds publish automatically when the package version is bumped.

```bash
pip install chumicro-repl-experimental
```

</details>

## Line mode

A terminal session starts in line mode, where your laptop edits each line and sends it when you press Enter.  Up-arrow recalls lines from earlier sessions on the same board.  Ctrl-R searches them.  `for index in r<Tab>` completes `range`.  A line that starts with `:` runs a command on your laptop:

| Command | What it does |
|---|---|
| `:help` | Lists every command. |
| `:edit` | Opens `$EDITOR`, or `vi` when `$EDITOR` is unset, holding your last 10 lines.  On save and exit, each non-empty line goes to the board in turn. |
| `:save NAME` | Saves your last 10 lines to `~/.chumicro-repl/snippets/NAME.py`. |
| `:load NAME` | Sends a saved snippet to the board line by line. |
| `:snippets` | Lists saved snippet names. |
| `:rescan` | Clears the cached board names, so the next Tab asks the board again.  Use it after an `import`. |
| `:quit` | Ends the session and leaves the board running, like Ctrl-X. |

History lives in one file per serial port: port `/dev/cu.usbmodem1101` keeps it at `~/.chumicro-repl/history/dev_cu_usbmodem1101/history.txt`.  Tab completion merges two sources: Python keywords and builtins, which need no board, and the board's own `dir()`, fetched on the first Tab and cached for the session.

## From Python

Run code on the board from a script and get its output back:

```python
from chumicro_deploy import Device
from chumicro_repl import ReplSession

device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

with ReplSession(device) as session:
    output = session.exec("import sys; print(sys.implementation)")
    print(output)  # (name='micropython', ...)
```

Follow a board after a deploy and fail the script on a traceback:

```python
from chumicro_repl import tail, ExitCode

result = tail(device, seconds=10)
if result is ExitCode.TRACEBACK_DETECTED:
    raise SystemExit("board crashed during follow-up tail")
```

## What's included

### Python API

| Symbol | What it does |
|---|---|
| `ReplSession(device)` | Context manager over the board's raw REPL.  `exec(code)` returns what the code printed, `call(function_name, *args, **kwargs)` returns a function's result, and `read_until(pattern, timeout=...)` waits for output |
| `InteractiveReplSession(device)` | `ReplSession` that names a failed start, prints the fix steps, and retries |
| `interactive_line(device)` | Opens line mode |
| `interactive(device)` | Opens passthrough mode, which reconnects for 60 seconds when the cable drops |
| `tail(device, seconds, *, fail_on_traceback=True)` → `ExitCode` | Prints the board's output for a window, highlights tracebacks, and returns why the window ended |
| `fetch_device_names(port)` → `list[str] \| None` | Fetches the board's `dir()` in one call, as line-mode Tab completion does |
| `build_default_completer(*, port=None, cache=None)` | Builds the `prompt_toolkit` completer line mode uses: keywords and builtins, plus the board's names when `port` is given |
| `BUILTIN_COMMANDS` / `LineModeContext` / `CompletionCache` | The `:command` table, the state a command handler receives, and the cache `:rescan` clears.  An extended table adds your own `:command` |
| `detect_patterns(text)` / `colorize(text)` | Find and color tracebacks, CircuitPython safe-mode and hard-fault messages, and MicroPython soft-reboot banners |
| `classify_session_failure(error)` → `ReplFailureKind` | Names why a session failed to start, for code that handles failures itself |
| `recovery_plan_for(kind)` → `RecoveryPlan` | Returns the headline and fix steps for a failure kind |

### Command

`chumicro-repl` and `python -m chumicro_repl` run the same tool.

| Form | What it does |
|---|---|
| `chumicro-repl --address PORT` | Opens the board's prompt, in line mode on a terminal |
| `chumicro-repl --address PORT --mode passthrough` | Sends every key to the board as it is pressed |
| `chumicro-repl --address PORT --tail SECONDS` | Prints the board's output for SECONDS, then exits |

`--mode auto`, the default, picks line mode on a terminal and passthrough when input is piped, because line mode reads from a terminal.

## Where this fits

`chumicro-repl` has no ChuMicro dependencies.  `pyserial` carries the serial traffic and `prompt_toolkit` edits lines.  [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) uses it for `repl` and `deploy --tail`.

[`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) copies code to a board, probes it, and installs firmware.  The two compose: `Deployer(device).deploy_diff(source)` sends the code, then `tail(device, seconds=10)` follows the board's first output.

## Examples

| Example | What it shows |
|---|---|
| `tail_after_deploy.py` | Following a board after a deploy and exiting on a traceback |
| `demo_repl_robustness.py` | An interactive walk through an unplugged cable, a held port, and a board that ignores Ctrl-C, showing the reconnect and retry behavior |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/repl/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/repl/experimental/)**

## Find this library

- **PyPI:** [chumicro-repl](https://pypi.org/project/chumicro-repl/)
- **Source:** [workbench/repl](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
