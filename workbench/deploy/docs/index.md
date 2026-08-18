---
title: "chumicro-deploy: deploy code to CircuitPython and MicroPython boards"
---

# chumicro-deploy

**Host-side transports and deploy tooling for CircuitPython and MicroPython boards.**

Push code onto a board, find out what firmware it is running, flash new firmware, and get a readable explanation when the serial port or the CIRCUITPY drive misbehaves. Runs on your laptop, not on the board.

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

result = Deployer(device).deploy_diff(source)
print(result.execute_output)
```

## What you get

- **Ship a directory, a dict you built in memory, or only the modules your entrypoint imports.** `DirectorySource` walks a host directory, `FileMapSource` takes a `dict` mapping on-device paths to contents, and `ImportGraphSource` reads the import statements out of your entrypoint and ships just what they resolve to.
- **Run from RAM while you iterate, write to flash when the code has to survive a reboot.** `Device(deploy_mode="ram")` pushes the payload over the serial REPL without touching the board's filesystem; `deploy_mode="flash"` writes it down. `Deployer.deploy_diff` also deletes on-device files that are no longer in the payload, so the board matches what you just sent.
- **Get told what went wrong and how to fix it.** `RecoveringDeployer` names the failure (another app is holding the port, the CIRCUITPY drive is gone, the REPL is stuck, macOS has wedged its FSKit filesystem extension) and prints the physical steps that clear it. Pass `prompt=input` for an Enter-to-retry loop; the default reports once and re-raises.
- **Check what a board is running before you deploy to it.** `probe_device` returns the runtime name, version, machine string, and CPU UID.
- **Reflash a board from a firmware URL.** `flash_firmware` covers the UF2 bootloader drive (Pi Pico family) and esptool over serial (ESP32 family). It enters the bootloader for you and asks you to hold the button only when that fails. `resolve_firmware_url` builds the CircuitPython download URL from a board ID and a version.
- **Keep the connection details in one `devices.yml` instead of in every script.** `chumicro_deploy.config.default.load_devices_yml` reads one entry by id, or the workspace default for a runtime. The schema is owned here, and `chumicro-repl` reads the same file.
- **Drive the transport layer yourself when you need to.** `chumicro_deploy.micropython_transport.MicropythonTransport` and `chumicro_deploy.circuitpython_transport.CircuitpythonTransport` expose the staging and execution steps directly. Two host prerequisites that cannot be installed for you raise named errors from `chumicro_deploy.host_platform`: `WindowsNotSupportedError` and `RsyncMissingError`.

## Companion: chumicro-repl

After a deploy, follow the board with [`chumicro-repl`](https://chumicro.github.io/ChuMicro/repl/stable/), the sister workbench tool that opens interactive serial sessions, tails the friendly REPL, and exposes a programmatic `ReplSession` for headless test fixtures. Both tools read the same `devices.yml` workspace file:

```python
from chumicro_deploy import Deployer
from chumicro_repl import tail, ExitCode

result = Deployer(device).deploy_diff(source)
if result.success:
    if tail(device, seconds=10) is ExitCode.TRACEBACK_DETECTED:
        raise SystemExit("board crashed during follow-up tail")
```

## Documentation

- [User Guide](guide.md): getting started, each surface explained, runtime notes.
- [API Reference](api.md): full API from the source docstrings.
- [Testing Helpers](testing.md): `FakeTransport`, `FakeSerialPort`, `FakeTime` for host-side tests.

## Install

```bash
pip install chumicro-deploy
```

No bundle registration needed. chumicro-deploy is a host tool, not on-device code.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · \
[PyPI](https://pypi.org/project/chumicro-deploy/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
