# chumicro-repl

Host-side serial REPL for CircuitPython and MicroPython boards with UTF-8 safe streaming and traceback highlighting.

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop to drive connected boards.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench pattern.

## Status

Pre-alpha.  Phase 2 minimum-viable core (Decision 0029): a pyserial-backed interactive TUI that matches the `mpremote` keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), a streaming pattern detector for CircuitPython / MicroPython tracebacks + safe-mode + soft-reboot banners with ANSI highlighting, a `tail()` function for deploy follow-ups, and a `ReplSession` context manager for programmatic `exec` / `call` / `read_until`.  See [the project-workspace workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/project-workspace.md) for what's ahead.

The larger "side-portal" feature set (history, editor handoff, snippets, device introspection commands, multi-device pane, session recording) is tracked in the separate [`repl-playground` workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/repl-playground.md) and builds on top of this core.

## What's here today

- `tail(device, seconds, fail_on_traceback=True)` — stream serial output for a window, highlight tracebacks as they arrive, return an `ExitCode`.  Used by deploy orchestration to follow a board after `deploy()` runs the entrypoint.
- `ReplSession(device)` — context manager wrapping the raw REPL.  `exec(code)`, `call(function_name, *args, **kwargs)`, and `read_until(pattern, timeout)` for test fixtures and headless automation.
- `interactive(device)` — the interactive TUI loop.  Prints a connection banner with keybinding hints, sends a carriage return on connect so the friendly REPL reprints its `>>>` prompt, forwards keystrokes to the board, and auto-reconnects through the same port factory when the cable drops mid-session (60 s budget by default; Ctrl-X aborts during the retry window).  Ctrl-X also quits a live session without rebooting the device.
- `InteractiveReplSession(device)` — sibling of `chumicro_deploy.InteractiveDeployer`.  Wraps `ReplSession` with classification + retry + coaching for session-start failures (port not found / busy / permission denied / raw-REPL unresponsive).  `classify_session_failure(error) -> ReplFailureKind` and `recovery_plan_for(kind) -> RecoveryPlan` are exported so callers can build their own orchestrator without using the wrapper.
- `detect_patterns(text)` / `colorize(text)` — streaming pattern detector + ANSI renderer for CP `Traceback`, `safe mode`, `Hard fault`, MP `Traceback`, and MP `MPY: soft reboot` banners.
- `chumicro-repl` CLI — `chumicro-repl --address /dev/cu.usbmodem...` for the bare path, or `chumicro-repl --devices-file devices.yml [--device <id> | --runtime <circuitpython|micropython>]` to read the same `devices.yml` schema `chumicro-deploy` owns.  `--tail SECONDS` toggles one-shot follow-mode.

## Install

```bash
pip install chumicro-repl
```

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
