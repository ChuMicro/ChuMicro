---
title: "chumicro-workspace: the CLI for CircuitPython and MicroPython projects"
---

# chumicro-workspace

**Host-side CLI for running ChuMicro projects on real boards.**

Register a board you just plugged in, scaffold a project, ship it, and watch the board's output stream back to your terminal.  Builds on [`chumicro-deploy`](https://chumicro.github.io/ChuMicro/deploy/stable/) for the transports, firmware flashing, and the `devices.yml` schema, and picks up [`chumicro-repl`](https://chumicro.github.io/ChuMicro/repl/stable/) when you ask for an interactive session or a tail.

## Quick example

```bash
# Day-zero: probe the board, register it in devices.yml, print what to run next.
# --demo also ships the built-in demo payload so the board does something.
chumicro-workspace bootstrap back-porch --address /dev/cu.usbmodem1101 --demo

# Iterate after that.
chumicro-workspace new garage/sensors/door_open
chumicro-workspace deploy garage/sensors/door_open
chumicro-workspace deploy garage/sensors/door_open --tail 30
```

## What you get

- **Bring up a board with one command.** `bootstrap` probes the runtime, writes the device into `devices.yml`, and tells you what to run next.  Pass `--demo` to ship a working payload in the same breath.
- **Scaffold a project, flat or nested.** `new garage/sensors/door_open` creates the tree and the namespace markers.  `--library` and `--workbench` scaffold a full chumicro-style library or a host-only tool instead.
- **Ship code and its config together.** `deploy` writes your project's files plus the merged runtime config to the board and starts it.  `--import-graph` walks the imports and ships only the modules the project actually reaches.  A board runs one project at a time; to change which one, deploy the other.
- **Watch what the board says.** `deploy <project> --tail` streams serial output for a window after the deploy; `repl` opens an interactive session against any registered board.
- **Keep credentials out of your source.** `secrets.toml` holds the wifi password and device defaults once; each project's `project_config.toml` overrides what it needs; the board gets the merged result as msgpack.
- **Keep `devices.yml` yours.** Comments and field order survive every rewrite.  Three zones decide who wins: user-owned fields (`id`, `description`, `deploy_mode`) are never overwritten, probed-always fields (`address`, `firmware_version`) refresh on each probe, and hardware-once fields (`runtime` and the `hardware:` block) need an explicit `--force`.
- **Install firmware.** `install-firmware` handles UF2 (Pi Pico family) and esptool (ESP32 family), entering the bootloader programmatically where it can and coaching you through it where it can't.
- **Find out what's broken.** `status` is the one-screen snapshot; `doctor` adds a Python version check and an AST scan for each project's `run()`.

## Documentation

- [User Guide](guide.md) for workflow walkthroughs end to end.
- [API Reference](api.md) for the public Python surface.

## Install

```bash
pip install chumicro-workspace
```

No bundle registration needed: chumicro-workspace is a host tool, not on-device code.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · \
[PyPI](https://pypi.org/project/chumicro-workspace/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
