# chumicro-repl

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Host-side serial REPL for CircuitPython and MicroPython boards — line-mode editor, passthrough TUI, programmatic `ReplSession`, and a `tail()` follower for deploy orchestration.**

Two interactive surfaces: a line-mode editor with persistent per-device history, `$EDITOR` handoff (`:edit`), saved snippets (`:save` / `:load` / `:snippets`), and Tab completion against keywords + the on-device namespace; or a byte-passthrough TUI with `mpremote`-compatible keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E) for raw-REPL framing and paste-mode flows.  UTF-8-safe streaming + in-stream traceback highlighting + auto-reconnect on cable drop apply to both.  Pluggable session-failure classifier so callers can build their own orchestrators on top.

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

That drops you into **line mode**: type `for index in r<Tab>` and Tab completes `range`; up-arrow recalls history; `:edit` opens `$EDITOR` with the recent buffer pre-seeded so multi-line blocks aren't a retype; `:save my-bringup` then `:load my-bringup` round-trips a snippet you'll paste again tomorrow.  Type `:help` to list every `:command`.

Need byte-passthrough (paste mode, raw-REPL framing, mpremote-shape Ctrl-C/Ctrl-D)?  Add `--mode passthrough`.

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
| `interactive_line(device)` | Line-mode TUI — host-side line editor with persistent per-device history, `:edit` / `:save` / `:load` / `:snippets` builtins, Tab against keywords + on-device `dir()` |
| `interactive(device)` | Passthrough TUI — `mpremote`-compatible keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), auto-reconnect through the configured serial-port factory, Ctrl-X quits without rebooting the device |
| `tail(device, seconds, *, fail_on_traceback=True)` → `ExitCode` | Stream serial output for a window, highlight tracebacks as they arrive, return one of the `ExitCode` enum values |
| `fetch_device_names(port, *, expression="")` → `list[str] \| None` | Drive the friendly→raw→`dir(<expression>)`→friendly round-trip in one call; the engine behind line-mode Tab completion.  Useful if you're embedding completion in your own session shape. |
| `build_default_completer(*, port=None, cache=None)` | `prompt_toolkit`-shaped completer wrapping `KeywordCompleter` + (optionally, when `port` is given) `DeviceCompleter`.  Caller-owned `cache` lets `:rescan`-style invalidation hook in. |
| `detect_patterns(text)` / `colorize(text)` | Streaming pattern detector + ANSI renderer for CP `Traceback` / `safe mode` / `Hard fault`, MP `Traceback` / `MPY: soft reboot` banners |
| `classify_session_failure(error)` → `ReplFailureKind` | Standalone classifier for building your own orchestrator on top of `ReplSession` |
| `recovery_plan_for(kind)` → `RecoveryPlan` | Canned headline + ordered fix-steps per failure kind |

### CLI

`chumicro-repl` (or `python -m chumicro_repl`).  Reads the same `devices.yml` schema [`chumicro-deploy`](../deploy/) owns.

| Form | What it does |
|---|---|
| `chumicro-repl --address /dev/cu.usbmodem...` | Interactive REPL on the bare port (line mode by default) |
| `chumicro-repl --devices-file devices.yml --device <id>` | Same, but pull connection details from the workspace registry |
| `chumicro-repl --devices-file devices.yml --runtime micropython` | Use the workspace's MP default device |
| `chumicro-repl --mode passthrough ...` | Byte-passthrough mode (mpremote-shape — for raw REPL framing / paste mode) |
| `chumicro-repl --tail SECONDS ...` | One-shot follow mode instead of interactive |

### Line-mode `:commands`

Type `:` at the start of a line to invoke a builtin command.  `:help` lists every command live in your session; the canonical six are:

| Command | What it does |
|---|---|
| `:edit` | Open `$EDITOR` with the recent input buffer pre-seeded; on save+exit, every non-empty line ships line-by-line.  Falls back to `vi` when `$EDITOR` is unset. |
| `:save NAME` | Persist the last 10 input lines to `~/.chumicro-repl/snippets/NAME.py`. |
| `:load NAME` | Replay a saved snippet line-by-line to the device. |
| `:snippets` | List saved snippet names. |
| `:rescan` | Drop the cached `dir()` so the next Tab re-queries the device.  Use after `import`-ing a new module — the completer otherwise serves the snapshot it took on first Tab. |
| `:quit` | Exit without rebooting the device.  Ctrl-D / Ctrl-C at the empty prompt do the same. |

History is persisted per-device under `~/.chumicro-repl/history/<sanitized-address>/history.txt` so a session on `back-porch` doesn't pollute one on `greenhouse`.  Up-arrow / Ctrl-R reverse search work normally.

### Tab completion

Two sources merge:

* **Keywords + builtins** — `print`, `range`, `for`, `import`, `True`, …  Always works, no device round-trip.  Covers most "what's that builtin called again" Tab presses.
* **On-device `dir()`** — populated on first Tab via a friendly-→raw-→`dir()`-→friendly round-trip (8–45 ms across the four-board canonical matrix; well below the perceptual "instant" threshold).  Cached for the session; `:rescan` invalidates after a new `import`.

The round-trip's friendly-banner reprint is consumed by the fetcher's read-until-`>>> ` so it never leaks into the rendered output.  See `fetch_device_names()` in `chumicro_repl.completion` if you're embedding the round-trip in your own session shape.

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
