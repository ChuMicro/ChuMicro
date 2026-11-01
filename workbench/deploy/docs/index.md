---
title: "chumicro-deploy: deploy code to CircuitPython and MicroPython boards"
---

# chumicro-deploy

**Copy Python code to a CircuitPython or MicroPython board and run it, install new firmware, or ask a board which firmware it runs, all from your laptop.**

`chumicro-deploy` is the lower-level tool under [`chumicro-workspace`](https://chumicro.com/ChuMicro/workspace/stable/).  Inside a ChuMicro workspace, `chumicro-workspace deploy` and `chumicro-workspace install-firmware` call this package and find each board by its name in `devices.yml`.  `chumicro-deploy` serves the work outside a workspace: a folder of code sent to a board by its serial port, a CI job, or a Python script that runs the deploy itself.

## Three commands

Each command takes the board's runtime and serial port.  On macOS, `ls /dev/cu.usbmodem*` lists the ports.  On Linux, `ls /dev/ttyACM*` lists them.

```bash
# Ask the board which firmware it runs.
chumicro-deploy probe --transport circuitpython --address /dev/cu.usbmodem1101

# Copy the my_app folder to the board and run my_app/code.py.
chumicro-deploy deploy --transport circuitpython --address /dev/cu.usbmodem1101 \
    --directory ./my_app --entrypoint /code.py

# Install CircuitPython 10.1.4 on a Raspberry Pi Pico W.
chumicro-deploy flash-firmware --transport circuitpython --address /dev/cu.usbmodem1101 \
    --url https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
```

`deploy` runs the code from the board's memory by default and leaves the files stored on the board alone.  `--deploy-mode flash` writes the files to the board instead, so the code runs again after a reset.  A flash deploy deletes every board file outside the folder, `settings.toml` included, unless `--no-wipe` is passed.  When a step fails, the tool names the cause, such as another app holding the serial port or a missing CIRCUITPY drive, lists the steps that fix it, and waits for Enter to retry.

## From Python

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

After a deploy, [`chumicro-repl`](https://chumicro.com/ChuMicro/repl/stable/) follows the board's output and opens its REPL.  Both tools read the same `devices.yml`.

```python
from chumicro_deploy import Deployer
from chumicro_repl import tail, ExitCode

result = Deployer(device).deploy_diff(source)
if result.success:
    if tail(device, seconds=10) is ExitCode.TRACEBACK_DETECTED:
        raise SystemExit("board crashed during follow-up tail")
```

## Documentation

- [User Guide](guide.md): the commands, `devices.yml`, failure recovery, then the Python API and reference tables.
- [API Reference](api.md): every public name, generated from the source docstrings.
- [Testing Helpers](testing.md): `FakeTransport`, `FakeSerialPort`, and `FakeTime` for host-side tests.

## Install

```bash
pip install chumicro-deploy
```

`chumicro-deploy` runs on your laptop, so the board needs no install of its own beyond CircuitPython or MicroPython firmware.

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Packages](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy) · \
[PyPI](https://pypi.org/project/chumicro-deploy/) · \
[Issues](https://github.com/ChuMicro/ChuMicro/issues)

</div>
