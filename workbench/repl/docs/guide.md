# User Guide

`chumicro-repl` ships three surfaces — an interactive TUI, a one-shot `tail()` follow-mode, and a programmatic `ReplSession` — that share a pyserial wrapper, a UTF-8 safe streaming decoder, and a pattern detector for the kinds of output that matter (tracebacks, safe-mode banners, hard faults, soft reboots).

## Install

```bash
pip install chumicro-repl
```

Host-only. No bundle registration or device-side install needed. After install, a `chumicro-repl` console script is on your PATH.

## Command-line interface

```bash
# Interactive TUI by serial path (no chumicro-deploy needed).
chumicro-repl --address /dev/cu.usbmodem14101

# Interactive TUI by devices.yml entry (chumicro-deploy installed).
chumicro-repl --devices-file devices.yml --device back-porch

# Pick the workspace's circuitpython default without naming the id.
chumicro-repl --devices-file devices.yml --runtime circuitpython

# Single-runtime devices.yml — no flags needed beyond --devices-file.
chumicro-repl --devices-file devices.yml

# One-shot tail for 5 seconds, fail on traceback (default).
chumicro-repl --address /dev/cu.usbmodem14101 --tail 5

# Tail without failing on traceback (useful for diagnosing crash loops).
chumicro-repl --address /dev/cu.usbmodem14101 --tail 30 --no-fail-on-traceback
```

When `--devices-file` is supplied, `chumicro-repl` resolves the target in this order:

1. **`--device <id>`** — wins outright.  Same semantics as `chumicro-deploy --device <id>`.
2. **`--runtime <circuitpython|micropython>`** — picks `defaults.<runtime>` from the file.  Use this when your workspace has both runtime defaults configured and you want one of them without memorizing the id.
3. **Neither flag** — the loader's single-runtime fallback applies.  When exactly one runtime default is set in the file, that wins; when both are set the loader raises and the CLI surfaces the error.

The schema and loader are owned by `chumicro_deploy.config.default.load_devices_yml` — no parallel parser, same `defaults:` / `devices:` shape `chumicro-deploy` reads.

When you connect, `chumicro-repl` prints a dim startup banner identifying the connection (`chumicro-repl · /dev/cu.usbmodem11401 · circuitpython · 115200 baud`) and the four keys you might want (`Ctrl-X exit · Ctrl-C interrupt · Ctrl-D soft-reboot · Ctrl-E paste`), then sends a single carriage return to nudge the friendly REPL into reprinting its `>>>` prompt — so you don't sit at a blank screen waiting for output that the device already printed before you connected.

The interactive TUI mirrors `mpremote repl`:

| Key | Effect |
|-----|--------|
| Ctrl-C | Forwarded — interrupts on-device. |
| Ctrl-D | Forwarded — soft-reboots the runtime. |
| Ctrl-E | Forwarded — enters MicroPython paste mode. |
| Ctrl-X | **Local exit** — quits the TUI without rebooting the board. |

All other keystrokes pass through unchanged. The board does its own line editing — arrow keys, backspace, history all work.

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
    print("clean tail — board ran without surfacing a traceback")
```

`tail()` accepts either a `chumicro_deploy.Device` or a bare port path string. Output is decoded UTF-8 safely (multi-byte code-points split across reads do not corrupt the stream) and ANSI-highlighted as it scrolls past — tracebacks are bold red, safe-mode banners are yellow, hard faults are red-on-red, MicroPython soft-reboot banners are dim cyan.

The window ends when:

- The `seconds` budget elapses → `ExitCode.OK`.
- `fail_on_traceback=True` (default) and a traceback / safe-mode / hard-fault block is detected → `ExitCode.TRACEBACK_DETECTED`.
- A `KeyboardInterrupt` reaches the read loop → `ExitCode.INTERRUPTED`.

Soft-reboot banners are informational and never end a tail early.

## Programmatic raw REPL — `ReplSession`

`ReplSession` is a context manager that puts the board into raw REPL on entry and exits cleanly. Three primitives:

```python
from chumicro_repl import ReplSession

with ReplSession("/dev/cu.usbmodem14101") as session:
    # Run a block — returns stdout as a UTF-8 string.
    output = session.exec("import os\nprint(os.uname())\n")

    # Call a named function with literal args, parse the repr.
    voltage = session.call("supervisor.runtime.usb_voltage")

    # Stream-read until a regex matches.  Useful for waiting on a
    # board signal before the next exec.
    captured = session.read_until(r"READY", timeout=5.0)
```

`exec(code, timeout=10.0)` returns stdout. If the board emitted stderr (typically because the code raised an exception), `ReplSession` raises `ReplSessionError` with the stderr block attached as the exception's `.stderr` attribute — raw REPL never raises a Python exception object across the wire, so surfacing it as a string is the closest host-side analogue.

`call(function_name, *args, **kwargs)` builds a `print(repr(<function_name>(*args, **kwargs)))` and parses the result via `ast.literal_eval`. Round-trips numbers, strings, bytes, tuples, lists, dicts, sets, booleans, and `None`. Anything else raises `ReplSessionError` because the repr is not a literal.

`read_until(pattern, timeout)` reads bytes from the port until the regex matches the accumulated decoded text. Operates on the friendly REPL too, so callers tailing a deploy can wait for a specific signal without bouncing through raw REPL.

The session accepts a `chumicro_deploy.Device`, a bare serial-port path, or any object with `.address` and `.baudrate` attributes. Tests inject `time` (a `TimeSource` protocol) and `port_factory` (any callable returning a `SerialPort` protocol) so the whole context is exercised without real hardware.

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

The `StreamingPatternDetector` is what `tail()` and the TUI use under the hood — it buffers a bounded amount of trailing context so a pattern that spans a chunk boundary still matches without retaining unbounded memory on long-running sessions. Use it directly for any custom streaming consumer.

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

- `FakeSerialPort` — drop-in for `serial.Serial`. Records writes; replays scripted `read_chunks`.
- `FakeKeyboard` — replays scripted keystrokes for `chumicro_repl.tui.run_loop`.
- `FakeTime` — deterministic seconds-domain time source. `monotonic()` is stable; `sleep()` advances the clock without a real wait.

## Runtime notes

The raw-REPL framing is identical between CircuitPython and MicroPython — both runtimes emit the same `OK<stdout>\x04<stderr>\x04>` shape on the same Ctrl-A/Ctrl-D handshake. The only divergence is what a friendly-REPL Ctrl-D prints: MicroPython emits `MPY: soft reboot` and CircuitPython is silent. `ReplSession` never leaves raw REPL during operation, so the divergence never surfaces there; it's a concern only for `tail()` (which highlights the soft-reboot banner) and the interactive TUI (which forwards Ctrl-D and shows whatever the board prints).

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

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl) · [PyPI](https://pypi.org/project/chumicro-repl/) · [Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
