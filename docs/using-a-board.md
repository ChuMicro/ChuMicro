# Inspect a board and recover files

New to the workbench? Begin with [Start here](start-here.md). This guide assumes macOS or Linux, a [prepared workbench](install.md), a registered `first-board`, a USB data connection, and MicroPython or CircuitPython.

Run laptop commands from the workbench root beside `run.py`. Close other serial monitors and use one serial session at a time.

## Watch current output

A tail is a timed output capture. Watch the current program without deploying anything:

```bash
python3 run.py repl --device first-board --tail 30
```

This captures only the next 30 seconds, then returns to the laptop prompt while the board program continues. A silent application produces no output. Past output that was not captured cannot be retrieved.

Tracebacks or faults end capture with failure, possibly before the complete traceback arrives. To capture future output across the whole window instead:

```bash
python3 run.py repl --device first-board --tail 30 --no-fail-on-traceback
```

`--no-fail-on-traceback` suppresses that failure exit. Status 0 with this option does not prove the program is healthy.

There is no universal live-state dashboard. To observe application values, add purposeful `print` calls and redeploy, as in the [first project's counter example](start-here.md).

## Inspect at the board prompt

A REPL is the board's Python prompt. Understand the runtime limits before interrupting:

- MicroPython may let you inspect still-reachable globals and module state.
- CircuitPython starts a fresh REPL VM, so the previous application's globals are unavailable.

Function locals may already be gone. For values unavailable afterward, arrange purposeful application output before stopping. Neither runtime promises paused execution that you can resume.

Open a passthrough session from the laptop:

```bash
python3 run.py repl --device first-board --mode passthrough
```

Press Ctrl-C to stop the running program. If CircuitPython shows `Press any key to enter the REPL. Use CTRL-D to reload.`, press Enter. Wait for the board's `>>>` prompt, not your laptop shell prompt. Enter each line separately there:

```python
dir()
import os
os.listdir()
```

Ctrl-D at empty input performs a soft restart: a fresh run with volatile state cleared. Ctrl-X leaves the local session without rebooting. Exit with Ctrl-X before running file commands.

## Recover selected deployed files

Deployed files are the board's copy. Capture needed state and output before using file tools. Back up before firmware changes, resets, or deployments with default cleanup. See [firmware guidance](troubleshooting/firmware-onto-a-new-board.md) when needed.

Using your file browser, create a separate laptop folder outside version control, such as `Documents/ChuMicro-board-backup`. `runtime_config.msgpack` may contain credentials. Never paste recovered credentials into an issue or agent chat.

### CircuitPython

Copy selected files or directories from the exposed `CIRCUITPY` USB drive into your backup folder using the file browser. Read and copy from the board rather than saving changes onto it. [Writing board files can trigger autoreload](https://learn.adafruit.com/welcome-to-circuitpython/creating-and-editing-code).

If the drive is missing, see [Mac CIRCUITPY recovery](troubleshooting/macos-circuitpy.md) or [board detection](troubleshooting/board-not-found.md).

### MicroPython

The workbench setup installs `mpremote`. After leaving the serial session with Ctrl-X, check its version, then list attached ports:

```bash
.venv/bin/mpremote version
```

```bash
.venv/bin/mpremote connect list
```

Choose the intended board explicitly to avoid copying from the wrong device. In the following commands, replace `<port>`, including angle brackets, with its actual path from the list. Keep the quotes.

**Before file access:** [mpremote 1.28 filesystem operations](https://docs.micropython.org/en/v1.28.0/reference/mpremote.html) interrupt the program and soft-reset the board before the first action. This file-copy route cannot retain live execution state. Capture state and output first.

List the board's current directory:

```bash
.venv/bin/mpremote connect "<port>" fs ls
```

Use actual filenames from this listing. Inspect nested directories with `fs ls` and a directory path. Only if `app.py` exists, read it with:

```bash
.venv/bin/mpremote connect "<port>" fs cat app.py
```

Recover that file to your laptop:

```bash
.venv/bin/mpremote connect "<port>" fs cp :app.py "<folder>/app.py"
```

Replace `<folder>`, including angle brackets, with your existing backup directory's path, retaining quotes. A `:` prefix marks a board path; an unprefixed path is local. For directory copies, put `-r` before the source and destination paths.

Check that the wanted files are visible and openable on your laptop. To start the application afterward, use Ctrl-D from an interactive REPL or the board reset.

## Understand the backup's limits

Board copies do not recover a whole workbench. Comments and docstrings may be stripped, `.mpy` files are bytecode rather than original source, and Git history is excluded. Tests and development files outside the deployed directory and import closure are unavailable. Host project configuration is merged into generated `runtime_config.msgpack`.

Keep the laptop workspace as your editable source of truth.

After recovering files, inspect a prospective deployment, substituting your project for `hello_board`:

```bash
python3 run.py deploy hello_board --device first-board --dry-run
```

This prints the intended file map without device writes. It is not an inventory of the actual board. Before a real deployment, read about [deployment cleaning and file persistence](troubleshooting/deploys-and-file-persistence.md).

## Work with an agent

Supply the runtime and board identity, failing command, complete redacted traceback, expected and actual output, and relevant source. Authorize the specific target and destructive actions separately. Allow only one device operation at a time. Until board actions are authorized, the task remains host diagnostics. See [working with agents](contributing/working-with-agents.md).
