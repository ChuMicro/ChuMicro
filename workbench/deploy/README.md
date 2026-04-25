# chumicro-deploy

Host-side device transports and deploy tooling for CircuitPython and MicroPython boards.

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop to deploy code and run tests on connected boards.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench pattern.

## Status

Pre-alpha.  Phase 1 complete (Decision 0029): host-side device transports, `Device` / `Deployer` facade, `FileSource` pluggability, `probe_device`, `flash_firmware` (UF2 + esptool), a thin `chumicro-deploy` CLI, and the `InteractiveDeployer` recovery layer are all shipped and hardware-verified on ESP32-S2, ESP32-S3, and Pi Pico W across CircuitPython and MicroPython.  See [the project-workspace workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/project-workspace.md) for what's ahead.

## What's here today

- `TransportProtocol` / `ExtendedTransportProtocol` — the duck-typed transport contract (Decision 0027).
- `MicropythonTransport` — mpremote-driven transport with `mount` and `copy` deploy modes (Decision 0028).
- `CircuitpythonTransport` — pyserial raw-REPL transport with `ram` and `flash` deploy modes.
- `build_circuitpython_bootstrap(_scripts)` — on-device test-harness bootstrap builders.
- `Deployer` / `InteractiveDeployer` — programmatic + interactive deploy orchestration.  The interactive variant classifies failures and coaches the user through a retry loop (unplug, raw-REPL stuck, drive ejected, flash copy failed, source traceback, macOS FSKit wedge).
- `detect_fskit_wedge` — macOS-only detector for the FSKit / DiskArbitration wedge that can leave CIRCUITPY drives unmountable; drives the automatic `CIRCUITPY_DRIVE_MISSING` → `MACOS_FSKIT_WEDGED` promotion.
- `probe_device` / `flash_firmware` / `resolve_firmware_url` — board probing and firmware flashing (UF2 + esptool paths).
- `chumicro_deploy.config.default.load_devices_yml` — built-in `devices.yml` loader. `Device.from_dict` / `Device.from_env` for explicit construction; entry-point discovery for third-party config formats. Accepts `device_id=...` for a specific entry, `runtime="circuitpython"` / `"micropython"` for the workspace's default, or neither when only one runtime default is set.
- `WindowsNotSupportedError` / `RsyncMissingError` from `chumicro_deploy.host_platform` — clean errors with install hints when the host environment is missing a prerequisite.
- `chumicro-deploy` CLI — `probe`, `flash`, `deploy`, `resolve-firmware-url` subcommands.
- `FakeTransport` / `FakeSerialPort` / `FakeTime` — deterministic host-side fakes for unit tests.

## Companion: chumicro-repl

[`chumicro-repl`](../repl/) is the sister workbench tool for opening interactive serial sessions and tailing the friendly REPL after a deploy.  Both packages consume the same `devices.yml` schema (owned here in `chumicro_deploy.config.default`), so a single workspace file points both at the same boards.  Use `chumicro_repl.tail(device, seconds)` to follow a deploy and fail-fast on a traceback; use `chumicro_repl.ReplSession(device)` for headless test fixtures over raw REPL.

## Install

```bash
pip install chumicro-deploy
```

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
