# chumicro-deploy

Host-side transports and deploy tooling for CircuitPython and MicroPython boards. Runs on your laptop, not on the board.

This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — it helps you manage boards from your laptop. It is not a library that runs on the microcontroller itself.

## Quick example

```python
from chumicro_deploy import Device, Deployer, FileMapSource

device = Device(
    transport="micropython",
    address="/dev/cu.usbmodem14101",
    deploy_mode="ram",
)
source = FileMapSource(
    {"/main.py": "print('hello from chumicro-deploy')"},
    entrypoint="/main.py",
)

result = Deployer(device).deploy(source)
print(result.execute_output)
```

## What you get

- **`Device`** — configure a target board (runtime, address, deploy mode). Construct it explicitly, from a dict via `Device.from_dict`, from env vars via `Device.from_env`, or load it from a `devices.yml` workspace file (see below).
- **`Deployer`** — write files onto the board and run the entrypoint.
- **`InteractiveDeployer`** — sibling deployer that classifies transport failures and coaches the user through a retry loop (unplug, drive ejected, REPL stuck, macOS FSKit wedge).
- **`FileSource` variants** — `FileMapSource` for in-memory dicts, `DirectorySource` for a host directory, `ImportGraphSource` to walk Python imports.
- **`probe_device`** — identify a connected board (runtime, version, machine, CPU UID).
- **`flash_firmware`** — download and flash firmware via UF2 (Pi Pico family) or esptool (ESP32 family), with programmatic bootloader entry + interactive fallback.
- **`resolve_firmware_url`** — turn a board ID + version into a download URL.
- **`chumicro_deploy.config.default.load_devices_yml`** — built-in `devices.yml` loader. Accepts `device_id` for a specific entry or `runtime` for the workspace's CP / MP default. The schema is owned here; `chumicro-repl` and any future workbench tool consume the same shape.
- **`chumicro_deploy.host_platform`** — `WindowsNotSupportedError` / `RsyncMissingError` for the two host prerequisites that aren't auto-installable.
- **`MicropythonTransport` / `CircuitpythonTransport`** — the lower-level transport layer if you need to drive stage / execute yourself.

## Companion: chumicro-repl

After a deploy, follow the board with **[`chumicro-repl`](../repl/)** — the sister workbench tool that opens interactive serial sessions, tails the friendly REPL, and exposes a programmatic `ReplSession` for headless test fixtures. Both tools consume the same `devices.yml` workspace file:

```python
from chumicro_deploy import Deployer
from chumicro_repl import tail, ExitCode

result = Deployer(device).deploy(source)
if result.success:
    if tail(device, seconds=10) is ExitCode.TRACEBACK_DETECTED:
        raise SystemExit("board crashed during follow-up tail")
```

## Documentation

- [User Guide](guide.md) — getting started, each surface explained, runtime notes.
- [API Reference](api.md) — full API from the source docstrings.
- [Testing Helpers](testing.md) — `FakeTransport`, `FakeSerialPort`, `FakeTime` for host-side tests.

## Install

```bash
pip install chumicro-deploy
```

No bundle registration needed — chumicro-deploy is a host tool, not on-device code.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · [PyPI](https://pypi.org/project/chumicro-deploy/) · [Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
