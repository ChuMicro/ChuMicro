# Workspace, devices, and secrets

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Three gitignored files live at the root of every ChuMicro workspace.  Each does what its name says.  `python scripts/run.py setup` materializes starter versions on first run; edit them as needs come up.

<br clear="left">

## workspace.yml: host-side tooling knobs

Linting / coverage settings, optional editable library clones, default deploy targets.  Sensible defaults cover everything; most contributors never touch this file.

```yaml
# library_sources:
#   chumicro-deploy: ../chumicro-deploy   # editable local clone

# deploy_targets:
#   my-project: pi-pico-w-circuitpython-board

# quality:
#   coverage_threshold: 85
#   lint:
#     tools: [ruff, chumicro-checks]
```

All blocks are optional.  Empty file = workspace defaults.

## devices.yml: the board registry

One entry per plugged-in board: serial port, runtime, deploy-mode default, and which board the IDE play button targets.

```bash
python scripts/run.py add-device pi-pico-w-mp --address /dev/cu.usbmodem1101
```

`add-device` probes the connected board, writes the entry, and (on first registration of each runtime) fills in the `defaults.<runtime>` pointer automatically.  Full flow + field reference in [Device Testing](device-testing.md).

## secrets.toml: runtime credentials for on-device code

Wifi password, MQTT broker host/port/auth: anything a deployed program needs at runtime that can't live in source control.  Edited once per clone.

```toml
[wifi]
ssid = "my-actual-network"
password = "my-real-wifi-password"

[mqtt.broker]
host = "10.0.0.5"
port = 1883
# [mqtt.broker.auth]
# username = "my-user"
# password = "my-mqtt-password"
```

At deploy time the host reads this file, deep-merges per-project `project_config.toml` + per-library `functional_tests/config.toml` overrides on top, flattens the result to dotted keys (`wifi.ssid`, `mqtt.broker.host`), and msgpack-encodes it into `/runtime_config.msgpack` on the board.  On-device code reads it back via `chumicro_config.load_runtime_config()`, the same API user-written programs use.

## Why three files

Three different jobs with three different gitignore promises and three different lifecycles:

- **`secrets.toml`** is "never commit, even by accident."  Folding it into either of the others would force them to inherit the same strict promise even though their content is share-safe.
- **`devices.yml`** changes whenever a board is plugged or unplugged.  Per-machine state, so drift between contributors would noise up shared history.
- **`workspace.yml`** changes when the workspace layout shifts.  Stable across most days.

The split lands per [Decision 0057](../../plans/decisions/0057-two-file-config.md).  Starter templates live under `workbench/workspace/src/chumicro_workspace/_payloads/` (tracked); the materialized files at the workspace root are gitignored.  `devices.yml` is the exception: its template lives with the code that reads it, at `workbench/deploy/src/chumicro_deploy/_payloads/devices.yml.template`, and materializes an empty `devices: []` registry for `add-device` to fill.

## Where to learn more

- [Device testing](device-testing.md): the device-side flow that reads all three files.
- [Decision 0057](../../plans/decisions/0057-two-file-config.md): the design rationale for the three-file split.
- [`workbench/workspace/`](../../workbench/workspace/): the package that materializes and validates each file.
