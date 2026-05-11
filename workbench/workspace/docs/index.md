# chumicro-workspace

**Host-side CLI for running ChuMicro projects on real boards.**

One command brings up a fresh board, scaffolds a project, deploys it, and tails the REPL.  Composes [`chumicro-deploy`](../deploy/) + [`chumicro-repl`](../repl/) with the workspace pieces those packages don't own: deploy-time config merge, a CLI that reads `workspace.yml`, three-zone `devices.yml` round-trip, board-state onboarding, firmware URL derivation, an import-graph deploy mode, and the boot-shim layout that lets one board host multiple projects.

## Quick example

```bash
# Day-zero bring-up — installs firmware, registers the board, deploys a demo,
# and tails the REPL.
chumicro-workspace bootstrap --with-demo

# Iterate after that.
chumicro-workspace new garage/sensors/door_open
chumicro-workspace deploy garage/sensors/door_open
chumicro-workspace repl garage/sensors/door_open
```

## What you get

- **`bootstrap`** — one-command day-zero board bring-up: firmware install, board onboarding, demo deploy, REPL follow.
- **`new`** — scaffold a project (flat or namespaced).  `--library` and `--workbench` flags scaffold a full chumicro-style library or workbench package alongside.
- **`deploy`** — write project files onto the board through three deploy modes (RAM, flash, boot-shim) with import-graph filtering.
- **`repl`** — open an interactive session against any registered board.
- **`devices.yml` round-trip** — three-zone YAML (defaults / devices / device-credentials) with safe rename + swap-board flows.
- **`workspace.yml` config merge** — flatten nested TOML config to dotted keys, merge per-library defaults, msgpack-encode for the device.
- **`install-firmware`** — UF2 (Pi Pico family) and esptool (ESP32 family), with programmatic bootloader entry + interactive fallback.
- **`doctor`** — health checks for the workspace, devices, and host platform.

## Documentation

- [User Guide](guide.md) — workflow walkthroughs end-to-end.
- [API Reference](api.md) — auto-generated reference for the public Python surface.

## Install

```bash
pip install chumicro-workspace
```

No bundle registration needed — chumicro-workspace is a host tool, not on-device code.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) · \
[PyPI](https://pypi.org/project/chumicro-workspace/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
