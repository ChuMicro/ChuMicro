# The three workspace config files

Every ChuMicro workspace materialises three gitignored config files at its root on first `setup`.  Each has a single job; together they configure boards, host-side tooling, and credentials without any of them duplicating the others.

| File | Owns | Flows onto the device? | Safe to share? |
|---|---|---|---|
| **`devices.yml`** | Board registry — id, runtime, serial address, deploy-mode default | No | Yes (no secrets) |
| **`workspace.yml`** | Host machinery — `library_sources`, `deploy_targets`, lint/coverage knobs | No | Yes (no secrets) |
| **`secrets.toml`** | Wifi password, MQTT broker auth, any other credentials a project inherits at deploy time | Yes — flattened into `/runtime_config.msgpack` | **Never** |

The split lands per [Decision 0057](../../plans/decisions/0057-two-file-config.md).  All three files are gitignored at the workspace root to keep local config out of the tree; the canonical starter templates live under `workbench/workspace/src/chumicro_workspace/_payloads/` (tracked).

## Where each file gets edited

```text
workspace-root/
├── devices.yml     # written by `chumicro-workspace add-device …`; hand-editable for tuning defaults
├── workspace.yml   # rarely edited; library_sources + deploy_targets + quality knobs
└── secrets.toml    # edited once per clone: wifi password, broker auth
```

### `devices.yml` — the board registry

`add-device` is the primary path; hand-editing is fine for tuning defaults.

```bash
python scripts/run.py add-device pi-pico-w-mp --address /dev/cu.usbmodem1101
```

Shape: a top-level `defaults:` block (which board is selected when no `--device` flag is passed) plus a `devices:` list with one entry per board.  Full schema in [device-testing.md § Configure `devices.yml`](device-testing.md#3-configure-devicesyml).

### `workspace.yml` — host machinery

Host-only.  Nothing here reaches a device.

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

All four blocks (`library_sources`, `deploy_targets`, `quality`, `environments`) are optional.  Empty file = workspace defaults.

### `secrets.toml` — credentials + device-bound defaults

The wifi password and broker auth a project needs at runtime.

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

Nested TOML tables on disk, flat dotted keys on the board (`config["wifi.ssid"]`, `config["mqtt.broker.host"]`).  Per-project `project_config.toml` (and per-library `functional_tests/config.toml`) deep-merge on top of these defaults at deploy time, then the result is flattened and msgpack-encoded into `/runtime_config.msgpack`.

## Why three files, not one

- **Different gitignore promises.**  `secrets.toml` is "never commit, even by accident."  `workspace.yml` and `devices.yml` are gitignored to avoid local-config drift, but contents are share-safe.
- **Different lifecycles.**  `devices.yml` changes when a board is plugged in.  `workspace.yml` changes when the workspace layout shifts.  `secrets.toml` is edited once per clone.
- **Different consumers.**  `devices.yml` feeds `chumicro-deploy`'s transport selection.  `workspace.yml` feeds the host-side workbench tooling.  `secrets.toml` feeds the deploy-time runtime-config merge that lands on the device.

Combining any two pairs would force the other one to inherit the strictest promise — `workspace.yml`-with-credentials would have to be strictly never-commit even though its host-machinery content is share-safe.

## Where to learn more

- [Device testing](device-testing.md) — the device-side flow that reads all three files.
- [Decision 0057](../../plans/decisions/0057-two-file-config.md) — the design rationale for the three-file split.
- [`workbench/workspace/`](../../workbench/workspace/) — the package that materialises and validates each file.
