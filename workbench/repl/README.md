# chumicro-repl

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Host-side serial REPL for CircuitPython and MicroPython boards: line-mode editor, passthrough TUI, programmatic `ReplSession`, and a `tail()` follower for deploy orchestration.**

Four surfaces, two of them interactive. Line mode is a host-side line editor with persistent per-device history, `$EDITOR` handoff (`:edit`), saved snippets (`:save` / `:load` / `:snippets`), and Tab completion against Python keywords plus the board's own namespace. Passthrough mode forwards every keystroke to the board with `mpremote`-compatible keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), which is what you want for raw-REPL framing and paste-mode flows. The other two surfaces are for scripts: `tail()` follows a board for a fixed window and stops on a traceback, and `ReplSession` runs code on the board and hands back stdout. Every surface decodes UTF-8 safely across chunk boundaries and highlights tracebacks as they scroll past. A pluggable session-failure classifier lets you build your own orchestrator on top.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family, small focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop, not on the board.

## Install

```bash
pip install chumicro-repl
```

`pyserial` and `prompt_toolkit` come along as dependencies. There is no board-side install; `chumicro-repl` talks to the CircuitPython or MicroPython runtime already on the board over USB serial. Native Windows isn't currently supported (the passthrough TUI needs POSIX `termios`); WSL2 works.

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
```

On a terminal that drops you into **line mode**. Type `for index in r<Tab>` and Tab completes `range`. Up-arrow recalls history from earlier sessions on the same board. `:edit` opens `$EDITOR` with the recent buffer pre-seeded, so a multi-line block isn't a retype. `:save my-bringup` then `:load my-bringup` round-trips a snippet you'll paste again tomorrow. Type `:help` to list every `:command`.

Need byte-passthrough (paste mode, raw-REPL framing, mpremote-shape Ctrl-C / Ctrl-D)? Add `--mode passthrough`.

Run something on the board from a script and capture stdout:

```python
from chumicro_deploy import Device
from chumicro_repl import ReplSession

device = Device(transport="micropython", address="/dev/cu.usbmodem1101")

with ReplSession(device) as session:
    output = session.exec("import sys; print(sys.implementation)")
    print(output)  # → "(name='micropython', version=(1,28,0), …)\n"
```

Follow a board after a deploy and fail the script on a traceback:

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
| `ReplSession(device)` | Context manager wrapping the raw REPL. `exec(code)`, `call(function_name, *args, **kwargs)`, `read_until(pattern, timeout)` |
| `InteractiveReplSession(device)` | Wraps `ReplSession` with classify + retry + coaching for session-start failures (mirrors the `chumicro_deploy.RecoveringDeployer` shape) |
| `interactive_line(device)` | Opens line mode: host-side line editor, persistent per-device history, `:edit` / `:save` / `:load` / `:snippets` builtins, Tab against keywords plus on-device `dir()` |
| `interactive(device)` | Opens passthrough mode: `mpremote`-compatible keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), auto-reconnect through the configured serial-port factory, Ctrl-X quits without rebooting the device |
| `tail(device, seconds, *, fail_on_traceback=True)` → `ExitCode` | Stream serial output for a window, highlight tracebacks as they arrive, return one of the `ExitCode` enum values |
| `fetch_device_names(port)` → `list[str] \| None` | Drive the friendly→raw→`dir()`→friendly round-trip in one call. The engine behind line-mode Tab completion, and useful if you're embedding completion in your own session shape. |
| `build_default_completer(*, port=None, cache=None)` | `prompt_toolkit`-shaped completer wrapping `KeywordCompleter` plus (when `port` is given) `DeviceCompleter`. A caller-owned `cache` lets `:rescan`-style invalidation hook in. |
| `BUILTIN_COMMANDS` / `LineModeContext` / `CompletionCache` | The line-mode command table, the state a command handler receives, and the namespace cache. Register your own `:command` by passing an extended table. |
| `detect_patterns(text)` / `colorize(text)` | Streaming pattern detector plus ANSI renderer for CircuitPython `Traceback` / `safe mode` / `Hard fault` and MicroPython `Traceback` / `MPY: soft reboot` banners |
| `classify_session_failure(error)` → `ReplFailureKind` | Standalone classifier for building your own orchestrator on top of `ReplSession` |
| `recovery_plan_for(kind)` → `RecoveryPlan` | Canned headline plus ordered fix-steps per failure kind |

### CLI

`chumicro-repl` (or `python -m chumicro_repl`). Opens a serial REPL on a given port.

| Form | What it does |
|---|---|
| `chumicro-repl --address /dev/cu.usbmodem...` | Interactive REPL on the bare port (line mode on a terminal) |
| `chumicro-repl --address ... --mode passthrough` | Byte-passthrough mode, for raw-REPL framing and paste mode |
| `chumicro-repl --address ... --tail SECONDS` | One-shot follow mode instead of interactive |

`--mode` takes `auto`, `line`, or `passthrough`. The default, `auto`, picks line mode on a terminal and passthrough when stdin is piped, since line mode needs interactive input.

### Line-mode `:commands`

Type `:` at the start of a line to invoke a builtin command. `:help` lists every command live in your session; the seven builtins are:

| Command | What it does |
|---|---|
| `:help` | List every registered command. |
| `:edit` | Open `$EDITOR` with the recent input buffer pre-seeded. On save and exit, every non-empty line ships line-by-line. Falls back to `vi` when `$EDITOR` is unset. |
| `:save NAME` | Persist the last 10 input lines to `~/.chumicro-repl/snippets/NAME.py`. |
| `:load NAME` | Replay a saved snippet line-by-line to the device. |
| `:snippets` | List saved snippet names. |
| `:rescan` | Drop the cached `dir()` so the next Tab re-queries the device. Use it after `import`-ing a new module, since the completer otherwise serves the snapshot it took on first Tab. |
| `:quit` | Exit without rebooting the device. Ctrl-D / Ctrl-C at the empty prompt do the same. |

History is persisted per-device under `~/.chumicro-repl/history/<sanitized-address>/history.txt` so a session on `back-porch` doesn't pollute one on `greenhouse`. Up-arrow and Ctrl-R reverse search work normally.

### Tab completion

Two sources merge:

* **Keywords and builtins:** `print`, `range`, `for`, `import`, `True`, and the rest. Always works, no device round-trip. Covers most "what's that builtin called again" Tab presses.
* **On-device `dir()`:** populated on first Tab via a friendly→raw→`dir()`→friendly round-trip. Cached for the session; `:rescan` invalidates it after a new `import`.

The round-trip's friendly-banner reprint is consumed by the fetcher's read-until-`>>> `, so it never leaks into the rendered output. See `fetch_device_names()` in `chumicro_repl.completion` if you're embedding the round-trip in your own session shape.

## Where this fits

No upstream ChuMicro dependencies; the third-party `pyserial` and `prompt_toolkit` do the transport and the line editing. Sister of [`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy), and used by [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) for deploy-and-tail flows.

## Companion: chumicro-deploy

[`chumicro-deploy`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) is the sister workbench tool for pushing code onto a board, probing identity, and flashing firmware. `chumicro-repl` is narrower, opening a serial REPL given a port path, so the two compose cleanly: `Deployer(device).deploy_diff(source)` writes the payload, then `tail(device, seconds=10)` (or any of the API entry points) follows the board for first-cycle output.

## Examples

| Example | What it shows |
|---|---|
| `tail_after_deploy.py` | Programmatic deploy → tail with traceback fail-fast |
| `demo_repl_robustness.py` | Walks the passthrough TUI through unplug / replug / Ctrl-C scenarios. A manual demo of the auto-reconnect and retry behavior. |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/repl/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/repl/experimental/)**

## Find this library

- **PyPI:** [chumicro-repl](https://pypi.org/project/chumicro-repl/)
- **Source:** [workbench/repl](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/repl)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
