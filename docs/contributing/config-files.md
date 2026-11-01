# Workspace, devices, and secrets

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

`workspace.yml`, `devices.yml`, and `secrets.toml` sit gitignored at the root of every ChuMicro workspace, this repository included.  `python scripts/run.py setup` writes a starter version of each on its first run, and leaves your edits alone after that.

<br clear="left">

## workspace.yml: host-side tooling knobs

`workspace.yml` holds lint and coverage settings, optional editable library clones, and the board each project deploys to by default.  Nothing in it reaches a board.  Its defaults suit this repository, so most contributors leave it alone.

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

Every block is optional, and an empty file means the workspace defaults.

## devices.yml: the board registry

`devices.yml` holds one entry per registered board, with its serial port, runtime, and deploy mode.  Its `defaults:` block picks the board each runtime's tests and IDE play buttons target.

```bash
python scripts/run.py add-device pi-pico-w-mp --address /dev/cu.usbmodem1101
```

[Device Testing § Register a board](device-testing.md#register-a-board-with-add-device) covers registration and every field.

## secrets.toml: runtime credentials for on-device code

`secrets.toml` holds what a deployed program needs at runtime and source control must never see: the wifi password, and the MQTT broker's address and login.  Edit it once per clone, replacing the placeholders `setup` wrote.

```toml
[wifi]
ssid = "your-network-name"
password = "your-wifi-password"

[mqtt]
# Only if your broker requires a login:
# username = "your-mqtt-user"
# password = "your-mqtt-password"

[mqtt.broker]
host = "your-broker-host"     # a hostname or IP address on your network
port = 1883
```

At deploy time the host reads `secrets.toml` and deep-merges a project's `project_config.toml`, or a library's `functional_tests/config.toml`, on top.  The overriding file wins at any nesting depth.  The host flattens the result to dotted keys such as `wifi.ssid` and `mqtt.broker.host`, and msgpack-encodes it into `/runtime_config.msgpack` on the board.  On-device code reads it back with `chumicro_config.load_runtime_config()`, the same call user-written programs make.

## Why three files

- **`secrets.toml`** must never reach a commit, even by accident.  Folding it into another file would hold that file's share-safe content to the same strict rule.
- **`devices.yml`** changes whenever you register, move, or remove a board.  It describes one laptop's boards, so committing it would fill shared history with every contributor's serial ports.
- **`workspace.yml`** changes when the workspace layout shifts, which is rare.

[Decision 0057](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0057-two-file-config.md) records the split.  The starter templates for `workspace.yml` and `secrets.toml` are tracked under `workbench/workspace/src/chumicro_workspace/_payloads/`.  The template for `devices.yml` lives with the code that reads it, at `workbench/deploy/src/chumicro_deploy/_payloads/devices.yml.template`, and produces an empty `devices: []` registry for `add-device` to fill.  The files produced at the workspace root are gitignored.

## Where to learn more

- [Device testing](device-testing.md): registering boards, and running the tests that read these files.
- [`chumicro-workspace` docs](https://chumicro.com/ChuMicro/workspace/stable/): the tool that writes and validates each file.
