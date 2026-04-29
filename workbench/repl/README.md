# chumicro-repl

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Host-side serial REPL for CircuitPython and MicroPython boards — interactive TUI, programmatic `ReplSession`, and a `tail()` follower for deploy orchestration.**

UTF-8-safe streaming, in-stream traceback highlighting, `mpremote`-compatible keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), auto-reconnect through the configured serial-port factory when the cable drops mid-session.  Pluggable session-failure classifier so callers can build their own orchestrators on top.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [See all libraries.](https://github.com/ChuMicro/ChuMicro#whats-in-the-box)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, not on the board.

## Installation

```bash
pip install chumicro-repl
```

`pyserial` and `prompt_toolkit` come along as dependencies.  No board-side install — `chumicro-repl` talks to the existing CP / MP runtime over USB serial.  Native Windows isn't currently supported (raises `WindowsNotSupportedError` from the underlying `chumicro-deploy` host-platform check); WSL2 works.

<details>
<summary>Experimental (pre-release) versions and channel switching</summary>

Pre-release builds publish automatically when the package version is bumped.

```bash
pip install chumicro-repl-experimental
```

</details>

## Quick example

Open an interactive REPL on a board:

```bash
chumicro-repl --address /dev/cu.usbmodem1101
# Or, with a workspace devices.yml:
chumicro-repl --devices-file devices.yml --device back-porch
```

Programmatic — exec something on the board and capture stdout:

```python
from chumicro_deploy import Device
from chumicro_repl import ReplSession

device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

with ReplSession(device) as session:
    output = session.exec("import sys; print(sys.implementation)")
    print(output)  # → "(name='micropython', version=(1,28,0), …)\n"
```

Follow a board after a deploy, fail the script on a traceback:

```python
from chumicro_repl import tail, ExitCode

result = tail(device, seconds=10)
if result is ExitCode.TRACEBACK_DETECTED:
    raise SystemExit("board crashed during follow-up tail")
```

## What's included

### Programmatic API

| Symbol | Description |
|---|---|
| `ReplSession(device)` | Context manager wrapping the raw REPL.  `exec(code)`, `call(function_name, *args, **kwargs)`, `read_until(pattern, timeout)` |
| `InteractiveReplSession(session)` | Wraps `ReplSession` with classify + retry + coaching for session-start failures (mirrors `chumicro_deploy.InteractiveDeployer` shape) |
| `interactive(device)` | Interactive TUI — `mpremote`-compatible keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), auto-reconnect through the configured serial-port factory, Ctrl-X quits without rebooting the device |
| `tail(device, seconds, *, fail_on_traceback=True)` → `ExitCode` | Stream serial output for a window, highlight tracebacks as they arrive, return one of the `ExitCode` enum values |
| `detect_patterns(text)` / `colorize(text)` | Streaming pattern detector + ANSI renderer for CP `Traceback` / `safe mode` / `Hard fault`, MP `Traceback` / `MPY: soft reboot` banners |
| `classify_session_failure(error)` → `ReplFailureKind` | Standalone classifier for building your own orchestrator on top of `ReplSession` |
| `recovery_plan_for(kind)` → `RecoveryPlan` | Canned headline + ordered fix-steps per failure kind |

### CLI

`chumicro-repl` (or `python -m chumicro_repl`).  Reads the same `devices.yml` schema [`chumicro-deploy`](../deploy/) owns.

| Form | What it does |
|---|---|
| `chumicro-repl --address /dev/cu.usbmodem...` | Interactive TUI on the bare port |
| `chumicro-repl --devices-file devices.yml --device <id>` | Same, but pull connection details from the workspace registry |
| `chumicro-repl --devices-file devices.yml --runtime micropython` | Use the workspace's MP default device |
| `chumicro-repl --tail SECONDS ...` | One-shot follow mode instead of TUI |

### Status

> Pre-alpha.  Decision 0029 Phase 2 minimum-viable core: pyserial-backed interactive TUI, streaming pattern detector + ANSI highlighting, `tail()` for deploy follow-ups, `ReplSession` for programmatic / headless use, `InteractiveReplSession` for retry coaching.  The richer "side-portal" feature set (history, editor handoff, snippets, device introspection commands, multi-device pane, session recording) is tracked in the separate [`repl-playground` workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/repl-playground.md) and builds on top of this core.

## Companion: chumicro-deploy

[`chumicro-deploy`](../deploy/) is the sister workbench tool for pushing code onto a board, probing identity, and flashing firmware.  Both packages consume the same `devices.yml` schema (owned in `chumicro_deploy.config.default`), so a single workspace file points both at the same boards.  Typical flow: `Deployer.deploy(source)` writes the payload, then `tail(device, seconds=10)` follows the board for first-cycle output.

## Examples

| Example | What it shows |
|---|---|
| `tail_after_deploy.py` | Programmatic deploy → tail with traceback fail-fast |
| `demo_repl_robustness.py` | Walks the interactive TUI through unplug / replug / Ctrl-C scenarios — manual demo of the auto-reconnect + retry behaviour |

## Developing this library

```bash
python scripts/run.py test --libraries repl
python scripts/run.py test-workbench-functional --workbench repl
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`.  See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/repl/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/repl/experimental/)**

## Find this library

- **PyPI:** [chumicro-repl](https://pypi.org/project/chumicro-repl/)
- **Source:** [workbench/repl](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
