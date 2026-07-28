# User Guide

`chumicro-repl` ships four surfaces: an interactive line-mode editor (default), a byte-passthrough TUI, a one-shot `tail()` follow-mode, and a programmatic `ReplSession`.

All four share a pyserial wrapper, a UTF-8-safe streaming decoder, and a pattern detector for the kinds of output that matter (tracebacks, safe-mode banners, hard faults, soft reboots).

## Install

```bash
pip install chumicro-repl
```

Host-only. No bundle registration or device-side install needed. After install, a `chumicro-repl` console script is on your PATH.

## Command-line interface

```bash
# Interactive REPL by serial path.  On a terminal this opens line mode.
chumicro-repl --address /dev/cu.usbmodem14101

# One-shot tail for 5 seconds, fail on traceback (default).
chumicro-repl --address /dev/cu.usbmodem14101 --tail 5

# Tail without failing on traceback (useful for diagnosing crash loops).
chumicro-repl --address /dev/cu.usbmodem14101 --tail 30 --no-fail-on-traceback
```

By default in a TTY, `chumicro-repl` opens **line mode**, a host-side line editor that buffers each line locally before shipping it to the device.  Switch to byte-passthrough with `--mode passthrough` if you need raw-REPL framing or paste-mode forwarding.

## Line mode

The default for terminal sessions.  `prompt_toolkit` reads a complete line on the host, giving you cursor edit, arrow keys, history navigation, and Ctrl-R reverse search, then ships the line to the device when you press Enter.  The device responds in the friendly REPL, and the response streams back through the same pattern detector and traceback highlighter `tail()` uses.

Lines starting with `:` are interpreted locally as builtin commands rather than shipped to the device:

| Command | What it does |
|---|---|
| `:help` | List every registered command. |
| `:edit` | Open `$EDITOR` with the last 10 input lines pre-seeded.  On save and exit, every non-empty line ships line-by-line to the device.  Falls back to `vi` when `$EDITOR` is unset.  Honors shell-shaped values: `EDITOR="code -w"` works. |
| `:save NAME` | Persist the last 10 input lines to `~/.chumicro-repl/snippets/NAME.py`. |
| `:load NAME` | Replay a saved snippet line-by-line. |
| `:snippets` | List saved snippet names. |
| `:rescan` | Drop the cached `dir()` so the next Tab re-queries the device.  Use it after `import`-ing a new module. |
| `:quit` | Exit without rebooting the device.  EOF (Ctrl-D) and Ctrl-C at an empty prompt do the same. |

```text
chumicro-repl · /dev/cu.usbmodem14101 · circuitpython · 115200 baud
:help to list commands · :quit to exit

>>> import wifi
>>> :rescan
line-mode: completion cache cleared; next Tab will re-query the device
>>> wifi.r<Tab>
            radio
>>> wifi.radio.connect("MySSID", "secret")
>>> :save bringup-wifi
line-mode: saved 3 line(s) to ~/.chumicro-repl/snippets/bringup-wifi.py
>>> :quit
line-mode: bye
```

History is persistent per-device at `~/.chumicro-repl/history/<sanitized-address>/history.txt` so a session on `back-porch` doesn't pollute one on `greenhouse`.

### Tab completion

Two sources merge in line mode:

* **Static catalog**, meaning Python keywords (`for`, `import`, `True`, and so on) and public builtins (`print`, `range`, `len`, and so on).  Always available; no device round-trip.
* **On-device `dir()`**, populated lazily on first Tab via a `print(repr(dir()))` round-trip through raw REPL.  Measured across four boards (Lolin S2 and Pi Pico W, each running CircuitPython and MicroPython), the round-trip took between 8 ms and 45 ms.  Cached for the session; `:rescan` invalidates it after a new `import`.

The friendly-banner reprint that the round-trip's `Ctrl-B` triggers is captured before line-mode resumes drawing, so it never leaks into your terminal.  Embedding the round-trip in your own shape?  Call `chumicro_repl.completion.fetch_device_names(port)`.

CircuitPython's bare REPL has an empty user namespace by design: `dir()` returns only `__name__` and `__file__` until you `import` something.  MicroPython pre-imports a handful of platform modules (`gc`, `os`, `machine`, `rp2`, `vfs`).  The static catalog covers what's typed most regardless.

## Passthrough mode (`--mode passthrough`)

When you need byte-exact forwarding for paste mode, raw-REPL framing, or mpremote-shape Ctrl-C / Ctrl-D semantics, pass `--mode passthrough`.  Keystrokes go straight to the device and the board does its own line editing.

```bash
chumicro-repl --mode passthrough --address /dev/cu.usbmodem14101
```

Startup prints a dim banner identifying the connection (`chumicro-repl · /dev/cu.usbmodem14101 · circuitpython · 115200 baud`) and the four keys you might want, then sends a single carriage return to nudge the friendly REPL into reprinting its `>>>`:

| Key | Effect |
|-----|--------|
| Ctrl-C | Forwarded; interrupts on-device. |
| Ctrl-D | Forwarded; soft-reboots the runtime. |
| Ctrl-E | Forwarded; enters MicroPython paste mode. |
| Ctrl-X | **Local exit**: quits the TUI without rebooting the board. |

All other keystrokes pass through unchanged.  The board does its own line editing, so arrow keys, backspace, and history all work, but they live on the device, not the host.  No `:` commands, no Tab completion against the host catalog, no persistent history file (the device's own history scrolls inside the runtime's `>>>` prompt).

Choose passthrough when you need byte-exact behavior or when you're piping input over stdin (line mode requires interactive input from a TTY); choose line mode for everyday inner-loop work.  `--mode auto` (the default) inspects `sys.stdin.isatty()` and picks the right one.

## Tail mode for deploy follow-ups

```python
from chumicro_deploy import Device
from chumicro_repl import tail, ExitCode

device = Device(
    transport="circuitpython",
    address="/dev/cu.usbmodem14101",
)

result = tail(device, seconds=10.0, fail_on_traceback=True)
if result is ExitCode.TRACEBACK_DETECTED:
    raise SystemExit("deploy crashed on the board")
elif result is ExitCode.OK:
    print("clean tail: board ran without surfacing a traceback")
```

`tail()` accepts either a `chumicro_deploy.Device` or a bare port path string. Output is decoded UTF-8 safely (multi-byte code-points split across reads do not corrupt the stream) and ANSI-highlighted as it scrolls past: tracebacks are bold red, safe-mode banners are yellow, hard faults are red-on-red, MicroPython soft-reboot banners are dim cyan.

The window ends when:

- The `seconds` budget elapses → `ExitCode.OK`.
- `fail_on_traceback=True` (default) and a traceback / safe-mode / hard-fault block is detected → `ExitCode.TRACEBACK_DETECTED`.
- A `KeyboardInterrupt` reaches the read loop → `ExitCode.INTERRUPTED`.

Soft-reboot banners are informational and never end a tail early.

## Programmatic raw REPL with `ReplSession`

`ReplSession` is a context manager that puts the board into raw REPL on entry and exits cleanly. Three primitives:

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    # Run a block, get stdout back as a UTF-8 string.
    output = session.exec("import os\nprint(os.uname())\n")

    # Call a named function with literal args, parse the repr.
    voltage = session.call("supervisor.runtime.usb_voltage")

    # Stream-read until a regex matches.  Useful for waiting on a
    # board signal before the next exec.
    captured = session.read_until(r"READY", timeout=5.0)
```

`exec(code, timeout=10.0)` returns stdout. If the board emitted stderr (typically because the code raised an exception), `ReplSession` raises `ReplSessionError` with the stderr block attached as the exception's `.stderr` attribute. Raw REPL never raises a Python exception object across the wire, so surfacing it as a string is the closest host-side analog.

`call(function_name, *args, **kwargs)` builds a `print(repr(<function_name>(*args, **kwargs)))` and parses the result via `ast.literal_eval`. Round-trips numbers, strings, bytes, tuples, lists, dicts, sets, booleans, and `None`. Anything else raises `ReplSessionError` because the repr is not a literal.

`read_until(pattern, timeout)` reads bytes from the port until the regex matches the accumulated decoded text. Operates on the friendly REPL too, so callers tailing a deploy can wait for a specific signal without bouncing through raw REPL.

The session accepts a `chumicro_deploy.Device`, a bare serial-port path, or any object with `.address` and `.baudrate` attributes. Tests inject `time` (a `TimeSource` protocol) and `port_factory` (any callable returning a `SerialPort` protocol) so the whole context is exercised without real hardware.

## Recover from session-start failures with `InteractiveReplSession`

`ReplSession` raises directly on a failed session-start, which is the deterministic surface programmatic callers want.  For interactive use, `InteractiveReplSession` wraps a `ReplSession` with classification, a retry-loop, and user-facing coaching, mirroring `chumicro_deploy.RecoveringDeployer`.

```python
from chumicro_repl import InteractiveReplSession

with InteractiveReplSession(device, max_attempts=3) as session:
    output = session.exec("print('hello')")
```

When the underlying session fails to open, the wrapper:

1. Classifies the exception into a `ReplFailureKind`: one of `PORT_NOT_FOUND`, `PORT_BUSY`, `PORT_PERMISSION_DENIED`, `RAW_REPL_UNRESPONSIVE`, or `UNKNOWN`.
2. Prints the matching `RecoveryPlan` (headline plus ordered fix-steps) to *output*.
3. Prompts the user via *prompt*: bare Enter retries; `q` / `quit` / `abort` / `exit` re-raises the last error.
4. After `max_attempts` attempts, the last exception re-raises.

`prompt` and `output` are injectable so you can plug the wrapper into a TUI dialog, a logging framework, or a test scripted with a queue of canned responses.

```python
from chumicro_repl import InteractiveReplSession, classify_session_failure, ReplFailureKind

# Custom orchestrator: classify directly without using the wrapper.
try:
    with ReplSession(device) as session:
        ...
except (OSError, ReplSessionError) as error:
    kind = classify_session_failure(error)
    if kind is ReplFailureKind.PORT_BUSY:
        ...  # close-the-other-tool flow
```

Mid-session disconnects (after the handshake completed) do *not* route through this layer.  Those are handled by the auto-reconnect loop in `tail()` and `run_loop()` (see `reconnect_seconds`).  Subclass `ReplSessionDisconnected` matters for that path; `InteractiveReplSession` matters for "the session never opened".

The interactive [`demo_repl_robustness.py`](https://github.com/ChuMicro/ChuMicro/blob/main/workbench/repl/examples/demo_repl_robustness.py) example walks every scenario against a real board: happy path, port-not-found (bogus address), port-busy (open the port elsewhere first), raw-REPL-unresponsive (board stuck in interrupt-disabled code), auto-reconnect during tail (yank and replug the cable), and abort during reconnect.

## Pattern detection and highlighting

```python
from chumicro_repl import detect_patterns, colorize, Theme

text = "running\n" + boards_traceback_output
matches = detect_patterns(text)
for match in matches:
    print(match.kind, match.start, match.end)

# Render with default colors.
print(colorize(text), end="")

# Custom theme.
theme = Theme(traceback="32")  # green tracebacks
print(colorize(text, theme=theme), end="")
```

The `StreamingPatternDetector` is the primitive `tail()` and the TUI build on. It buffers a bounded amount of trailing context so a pattern that spans a chunk boundary still matches without growing memory on long-running sessions. Use it directly for any custom streaming consumer.

## Test fakes

Host-side tests can drive every surface without real hardware:

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

Three fakes are exposed under `chumicro_repl.testing`:

- `FakeSerialPort`, a drop-in for `serial.Serial`. Records writes; replays scripted `read_chunks`.
- `FakeKeyboard`, which replays scripted keystrokes for `chumicro_repl.tui.run_loop`.
- `FakeTime`, a deterministic seconds-domain time source. `monotonic()` is stable; `sleep()` advances the clock without a real wait.

## Runtime notes

The raw-REPL framing is identical between CircuitPython and MicroPython. Both runtimes emit the same `OK<stdout>\x04<stderr>\x04>` shape on the same Ctrl-A/Ctrl-D handshake. The only divergence is what a friendly-REPL Ctrl-D prints: MicroPython emits `MPY: soft reboot` and CircuitPython is silent. `ReplSession` never leaves raw REPL during operation, so the divergence never surfaces there; it's a concern only for `tail()` (which highlights the soft-reboot banner) and the passthrough TUI (which forwards Ctrl-D and shows whatever the board prints).

Pattern detection covers:

| Kind | Source | When it appears |
|------|--------|-----------------|
| Traceback | both | An uncaught exception. |
| Safe mode | CircuitPython | Repeated crashes or supervisor reload into a broken state. |
| Hard fault | CircuitPython | A crash below the Python-exception layer. |
| Soft reboot | MicroPython | Ctrl-D in the friendly REPL or `machine.soft_reset()`. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · \
[PyPI](https://pypi.org/project/chumicro-repl/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
