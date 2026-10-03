---
title: Install or update board firmware
---

<span id="getting-firmware-onto-a-new-board"></span>

# Install or update board firmware

Firmware is the board’s Python runtime: MicroPython or CircuitPython. The bootloader is its firmware-installation mode. Board registration saves an identity that your laptop tools use to find and work with the board.

## Choose your route and preserve files

Check [supported boards and installation requirements](../install.md#board-support) for your exact model and variant. ChuMicro requires MicroPython 1.27 or later, or CircuitPython 10.1 or later. Choose a stable release matching your board and library-installation route. You do not need a preview build.

**Warning:** Flashing may erase board-only files and settings. Copy wanted files first, including credentials, to a laptop folder outside Git. Follow the [board-file backup instructions](../start-here.md#copy-off-files-you-want-to-keep).

For MicroPython without a prepared laptop, complete [workbench setup](../start-here.md) before using those backup instructions. For CircuitPython with an exposed drive, copy files through your file browser. A blank board with nothing you want to keep can proceed directly.

<span id="reset-board-erased-my-settingstoml-and-bootpy"></span>

`reset-board` is not firmware installation: it wipes the user filesystem without changing firmware. It removes all user files, including `settings.toml` and hand-edited `boot.py`. For deliberate filesystem recovery, follow the separate [filesystem-wipe procedure](../contributing/device-testing.md#wiping-a-boards-filesystem), which covers target selection and modes. Back up before that task too.

Choose the route that fits:

- **First installation or no registration:** follow the first-installation section below.
- **Registered board, same runtime:** use the workbench update below for UF2 or esptool. For other methods, follow your exact board’s official guide.
- **Switching runtimes:** follow the first-installation route, then register again. The old saved transport identity is unsuitable for the new runtime.

<span id="no_python_runtime-no-firmware-detected"></span>

## Install firmware for the first time

Use this route for `NO_PYTHON_RUNTIME` or “no Python detected” too. That symptom alone does not identify the board or its installation method.

Open the official catalog for your intended runtime:

- [MicroPython downloads](https://micropython.org/download/): your board’s page provides image choices and installation instructions.
- [CircuitPython downloads](https://circuitpython.org/downloads): your board’s page provides the download and a linked installation guide.

Find your exact board model and variant. An MCU-family name alone is not enough to choose an image. Download the matching image and follow its board-specific instructions. This route does not require `devices.yml`, a workbench, or ChuMicro registration.

Use a USB data cable. Bootloader entry depends on the board. For Pico W, use the [Pico W firmware steps](../start-here.md#install-firmware): hold BOOTSEL while connecting to enter its USB UF2 bootloader. The `RPI-RP2` drive name applies to Pico/Pico W, not every blank board.

Copy a UF2 file only when the board’s installation guide tells you to. Serial-flash boards need their guide’s flashing procedure instead.

Check completion using the indicators in the selected board guide. CircuitPython USB-drive builds expose `CIRCUITPY`. Pico W running MicroPython uses serial communication without a mounted drive. Other boards’ drive behavior depends on the board.

If your workbench is not ready, complete [laptop and workbench preparation](../start-here.md), then [register the board](../start-here.md#register-the-board). With a prepared workbench, go directly to registration. After switching runtimes, register under a new device name.

Adding `--url` to the workspace install command only overrides the image. It does not remove the registered-device requirement.

<span id="a-new-board-registers-fine-then-hits-missing-module-errors-at-deploy"></span>

## Update a registered board

These commands require a prepared `my-workbench` and an already registered `first-board`. Preserve your files before continuing.

Open a laptop terminal in `my-workbench`, beside `run.py`. Replace `first-board` in every command if your saved device name differs.

Choose the method specified by your board’s installation guide. For a registered UF2 board, run:

```bash
python3 run.py install-firmware --method uf2 --device first-board
```

Without `--url`, the tool derives the image URL from saved hardware information. If it cannot resolve one, supply the matching official image URL with `--url`.

For a registered ESP32 using serial flashing, use the command below. Replace `<firmware-url>` with the actual direct `.bin` image URL and `<offset>` with the exact offset from that image’s official instructions. Remove the angle brackets. The offset depends on the board and image; never assume a default applies to every ESP32 firmware.

**Warning:** `--erase` erases user flash before writing. Back up wanted files and settings before running this command.

```bash
python3 run.py install-firmware --method esptool --device first-board --url "<firmware-url>" --offset <offset> --erase
```

For installation methods other than UF2 or esptool, follow your exact board’s official guide from the runtime catalog above, then verify below.

The tool downloads the image, then flashes it. Follow its printed prompts for physically entering the bootloader.

<span id="esp32-s2-goes-silent-entering-the-bootloader-esptool-reports-no-serial-data-received"></span>

If automatic bootloader entry fails or you see `No serial data received`, close programs using the serial port and follow your board’s manual bootloader steps. On an ESP32 with BOOT/RESET buttons, hold BOOT, press and release RESET, then release BOOT. Follow the prompt when the new port appears.

### Verify the update

For a same-runtime update, run this from the same workbench:

```bash
python3 run.py probe --device first-board
```

Check the `runtime:` and `version:` fields against your intended runtime and the minimum versions above. The probe reports these values but does not classify them against ChuMicro’s support floors. If the version is below the minimum, install the correct supported image before debugging libraries.

If a version-floor hint omits `--method`, use the complete commands on this page. For further connection trouble, follow [Board not found](board-not-found.md).
