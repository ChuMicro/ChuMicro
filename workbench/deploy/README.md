# chumicro-deploy

Host-side device transports and deploy tooling for CircuitPython and MicroPython boards.

Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) workspace.  Workbench tool — runs on your laptop to deploy code and run tests on connected boards.  See [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md) for the workbench pattern.

## Status

Pre-alpha.  Currently a lift-and-shift of `support/device_transport/` into a publishable workbench package — the high-level `Device` / `Deployer` facade, `FileSource` pluggability, `probe_device`, firmware flashing, and the CLI are still ahead.  See [Phase 1 of the project-workspace workstream](https://github.com/ChuMicro/ChuMicro/blob/main/plans/workstreams/project-workspace.md) for the sequencing.

## What's here today

- `TransportProtocol` / `ExtendedTransportProtocol` — the duck-typed transport contract (Decision 0027).
- `MicropythonTransport` — mpremote-driven transport with `mount` and `copy` deploy modes (Decision 0028).
- `CircuitpythonTransport` — pyserial raw-REPL transport with `ram` and `flash` deploy modes.
- `build_circuitpython_bootstrap(_scripts)` — on-device test-harness bootstrap builders.
- `FakeTransport` — deterministic host-side fake for unit tests.

## Install

```bash
pip install chumicro-deploy
```

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
