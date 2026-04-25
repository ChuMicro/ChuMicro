# chumicro-repl

Host-side serial REPL for CircuitPython and MicroPython boards with UTF-8 safe streaming and traceback highlighting.

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop to drive connected boards.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench pattern.

## Status

Pre-alpha.  Phase 2 minimum-viable core (Decision 0029): a pyserial-backed interactive TUI that matches the `mpremote` keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E), a streaming pattern detector for CircuitPython / MicroPython tracebacks + safe-mode + soft-reboot banners with ANSI highlighting, a `tail()` function for deploy follow-ups, and a `ReplSession` context manager for programmatic `exec` / `call` / `read_until`.  See [the project-workspace workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/project-workspace.md) for what's ahead.

The larger "side-portal" feature set (history, editor handoff, snippets, device introspection commands, multi-device pane, session recording) is tracked in the separate [`repl-playground` workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/repl-playground.md) and builds on top of this core.

## What's here today

- `tail(device, seconds, fail_on_traceback=True)` — stream serial output for a window, highlight tracebacks as they arrive, return an `ExitCode`.  Used by deploy orchestration to follow a board after `deploy()` runs the entrypoint.
- `ReplSession(device)` — context manager wrapping the raw REPL.  `exec(code)`, `call(function_name, *args, **kwargs)`, and `read_until(pattern, timeout)` for test fixtures and headless automation.
- `interactive(device)` — the interactive TUI loop.  Forwards keystrokes to the board; Ctrl-X quits without rebooting the device.
- `detect_patterns(text)` / `colorize(text)` — streaming pattern detector + ANSI renderer for CP `Traceback`, `safe mode`, `Hard fault`, MP `Traceback`, and MP `MPY: soft reboot` banners.
- `chumicro-repl` CLI — `chumicro-repl --device <id> --devices-file devices.yml` for an interactive session; `--tail SECONDS` for one-shot follow-mode.

## Install

```bash
pip install chumicro-repl
```

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
