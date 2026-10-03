---
title: Installing ChuMicro libraries on CircuitPython, MicroPython, and CPython
---

# Installing ChuMicro libraries

Install libraries on a CircuitPython or MicroPython board, or into CPython for host-side library tests. CPython is a test seam, not a deployment target.

Before choosing a route, board users should check [Board support](#board-support), including chip and firmware. Laptop test users need Python 3.11 or later.

- Existing workbench: [Workbench project](#workbench-project).
- Standalone CircuitPython board: [CircuitPython with circup](#circuitpython-with-circup).
- Standalone MicroPython board: [MicroPython with mpremote](#micropython-with-mpremote).
- Laptop library tests: [CPython with pip](#cpython-with-pip).

<span id="quick-install-stable-channel"></span>

<span id="experimental-pre-release-channel"></span>

## Names and channels

Use `chumicro-timing` with pip, but `chumicro_timing` for circup, mip, workbench acquisition, and imports. For another library, substitute its corresponding names from the [ChuMicro library table](https://github.com/ChuMicro/ChuMicro#the-libraries), which covers all 15 libraries.

| Where | Stable | Experimental |
|---|---|---|
| PyPI (pip) | `chumicro-timing` | `chumicro-timing-experimental` |
| Bundle (circup, mip), a GitHub repository supplying libraries | [`ChuMicro/ChuMicro-Bundle`](https://github.com/ChuMicro/ChuMicro-Bundle) | [`ChuMicro/ChuMicro-Bundle-Experimental`](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental) |
| Workbench | `--channel stable` (default) | `--channel experimental` |
| Import name | `chumicro_timing` | `chumicro_timing` |

Stable versions require maintainer promotion. Merged version bumps publish automatically to experimental and may break. New libraries remain experimental-only until promotion. Each route ends with experimental instructions.

Channel and file form are separate choices: stable/experimental selects the publication; source/bytecode selects the files.

Output placeholders such as `<version>` and `<date>` represent your release’s values.

## Board support

Boards need at least **256 KB RAM**, **2 MB flash**, and firmware providing `collections.deque`: full-build CircuitPython or a MicroPython `EXTRA_FEATURES`+ port. Matching chip and version alone is insufficient.

Use **MicroPython 1.27 or later** or **CircuitPython 10.1 to 10.x**.

- ESP32-S2/S3 and ESP32-C3/C6: both runtimes. For drive-less CircuitPython, see [CircuitPython with circup](#circuitpython-with-circup).
- Classic ESP32: MicroPython only. CircuitPython has a program-corruption issue; see [Known board quirks](troubleshooting/board-quirks.md).
- RP2040/RP2350: supported, including Pico, Pico W, and Pico 2.
- STM32: supported with at least 256 KB RAM.

ESP8266, SAMD21, SAMD51, nRF52, and other chips are excluded or untested. Check each library README’s **Platform support** for library-specific restrictions.

**Warning:** Installing firmware may erase board files. Back up valuable board-only files first.

For replacement firmware, choose your exact board and a supported release at [CircuitPython downloads](https://circuitpython.org/downloads) or [MicroPython downloads](https://micropython.org/download/), then follow that board’s installation instructions. Workbench users can follow [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md).

<span id="project-workspaces"></span>

## Workbench project

After [Start here](start-here.md), you have `hello_board` deployed to `first-board` and timing acquired through Runner. This repeats the acquisition/import/check pattern for reuse with other libraries.

Run commands on your laptop from `my-workbench`, your Start-here project folder. The wrapper selects `.venv`, a virtual environment separating its Python interpreter and packages from system Python and other environments by default. Local pip installs go there; activation is optional.

In linked troubleshooting, `chumicro-workspace <command>` means `python3 run.py <command>` from `my-workbench`.

With laptop network access, acquire the sources:

```bash
python3 run.py library add chumicro_timing
```

Output includes:

```text
Added chumicro_timing v<version> (stable)
```

Files go into `libraries/chumicro_timing/`; dependencies get individual `libraries/<dep>/` folders. At `pull <dep>? [Y/n]`, Enter accepts. Timing has no dependencies, so that prompt does not appear.

Conditional dependency output looks like:

```text
  + chumicro_<dep> v<version>
```

Output may also include `Updated pyrightconfig.json (...)` when missing source paths are added. This editor update is harmless to installation.

Edit `projects/hello_board/app.py`. Add this at module level above `def run()`, retain the existing function, and save:

```python
import chumicro_timing
```

Check the deployment map:

```bash
python3 run.py deploy hello_board --device first-board --dry-run
```

In the output, look for `/lib/chumicro_timing/__init__.py` and any additional imported timing modules under `/lib/chumicro_timing/`. Runner already reaches timing, so the explicit import need not add new entries. If timing paths are missing, check the import spelling, save, and retry.

Deployment includes project imports and their transitive modules.

**Warning:** Default deployment removes circup/mip copies from the board. Acquire workbench libraries through `library add`.

Deploy and watch board output for 30 seconds:

```bash
python3 run.py deploy hello_board --device first-board --tail 30
```

Successful output shows deployment completion, then the recurring Start-here greeting and loop counter, without `ImportError`. For an unresolved-import refusal or traceback, use the matching [troubleshooting item](#troubleshooting-installs).

**Experimental.** This selects experimental for the library and its dependency closure, including when re-adding an existing library:

```bash
python3 run.py library add chumicro_timing --channel experimental
```

Output includes:

```text
Added chumicro_timing v<version> (experimental)
```

Run the deployment command above again to update the board.

<span id="circuitpython-circup-and-the-chumicro-bundle"></span>

## CircuitPython with circup

On C3/C6 builds without a `CIRCUITPY` drive, use [circup](https://github.com/adafruit/circup)’s web workflow with `--host` and `--password`, following its setup instructions. Workbench users can instead deploy over serial through [Workbench project](#workbench-project).

For mounted-drive installs, read the first line of `CIRCUITPY/boot_out.txt`. Expected output pattern:

```text
Adafruit CircuitPython <version> on <date>; <board>
```

Require 10.1 to 10.x. Otherwise, select that range for your exact board at [CircuitPython downloads](https://circuitpython.org/downloads), follow its installation guide, and heed the [Board support](#board-support) backup warning.

On your laptop with Python 3.11 or later, [create and activate a virtual environment](https://docs.python.org/3/library/venv.html). Install:

```bash
pip install circup
```

Alternatively, [install pipx](https://pipx.pypa.io/stable/how-to/install-pipx.html) and run `pipx install circup`. pipx gives each tool its own environment and makes its command available across shells.

Register the bundle once per OS user/computer:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
```

Output includes `Added ChuMicro/ChuMicro-Bundle`, the bundle URL, and download lines. Without a board, `Auto locating USB Disk based device failed` can appear even when registration succeeds.

With `CIRCUITPY` mounted, install:

```bash
circup install chumicro_timing
```

Successful output ends with:

```text
Installed 'chumicro_timing'.
```

This installs precompiled Python bytecode (`.mpy`) into `CIRCUITPY/lib/chumicro_timing/`. Dependencies occupy individual sibling library folders.

For detection trouble with a mounted or renamed drive, or multiple boards, specify `<folder>`, the drive root containing `boot_out.txt`:

```bash
circup --path <folder> install chumicro_timing
```

For an absent drive, see [Troubleshooting installs](#troubleshooting-installs). If the library is already installed, upgrade:

```bash
circup install --upgrade chumicro_timing
```

Successful upgrades end with the same output line.

**Experimental.** The registry is per OS user, shared across that user’s boards. For each module, the earliest registered bundle containing it wins silently, without a conflict warning.

If stable is registered, remove it:

```bash
circup bundle-remove ChuMicro/ChuMicro-Bundle
```

At `Do you want to remove that bundle ?`, answer `y`. Output confirms `Removing the bundle from the local list`.

If stable was absent, skip removal. With a mounted board, run:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install --upgrade chumicro_timing
```

Expect the same installation success output. Check the registry:

```bash
circup bundle-show
```

Output must include `ChuMicro/ChuMicro-Bundle-Experimental`, without `ChuMicro/ChuMicro-Bundle` as a separate entry. Keep other bundles registered.

<span id="micropython-mip"></span>

## MicroPython with mpremote

[mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) controls MicroPython’s mip installer from your laptop. With Python 3.11 or later and an [activated virtual environment](https://docs.python.org/3/library/venv.html), install:

```bash
pip install mpremote
```

Alternatively, use [pipx](https://pipx.pypa.io/stable/how-to/install-pipx.html) with `pipx install mpremote`.

Connect the board over USB; subsequent commands use it. Check firmware:

```bash
mpremote exec "import sys; print(sys.version)"
```

Output pattern:

```text
3.4.0; MicroPython v<version> on <date>
```

Read the version after `MicroPython v`. Below 1.27, select your exact board and a 1.27-or-later release at [MicroPython downloads](https://micropython.org/download/), following its installation instructions and the [Board support](#board-support) backup warning.

<span id="pre-compiled-mpy-bytecode"></span>

Choose one file form before installing. Source (`.py`) is the default. Precompiled bytecode (`.mpy`) from `mpy6/` supports MicroPython 1.27 or later and reduces compiler RAM during import, useful for import-time `MemoryError`. MicroPython prefers `.py` over `.mpy`: keep one form per library.

Installation needs laptop network access, not board networking. Run only one alternative.

**Source:**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

**Bytecode:**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
```

Output includes `Installing .../<name>/package.json to <lib folder>`, package/dependency lines, and final `Done`. Dependencies get individual sibling library folders.

Use the printed lib target: examples are `/lib` on ESP32/RP2, `/flash/lib` on STM32 internal flash, and `/sd/lib` on STM32 with mounted SD. Substitute that target in the `/lib` listing and cleanup examples below.

Check installation:

```bash
mpremote ls /lib
```

Output should include the `chumicro_timing/` folder.

**Changing an existing install’s form.** Remove timing and every dependency folder before installing the other form:

```bash
mpremote rm -r :/lib/chumicro_timing
```

Get dependency names from installation lines immediately before `/package.json`; repeat cleanup for each. Keep the same printed lib target throughout cleanup and reinstall. Keep the channel unchanged: use the other command from the stable pair above or experimental pair below.

**Experimental.** Choose source or bytecode, not both. Existing matching-form files are overwritten. To change form, follow the grouped cleanup procedure first, keeping the channel unchanged.

**Source:**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing
```

**Bytecode:**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/mpy6/chumicro_timing
```

<span id="cpython-pip"></span>

## CPython with pip

For host-side library tests, use your laptop with Python 3.11 or later and an [activated virtual environment](https://docs.python.org/3/library/venv.html). Install the library and its dependencies:

```bash
pip install chumicro-timing
```

This prepares CPython’s test seam, not a laptop-application deployment.

**Experimental.** Stable and experimental distributions overlap at import-package files. Experimental libraries depend on experimental ChuMicro distributions.

Inspect installed packages with `pip list`. Uninstall installed stable members of the [ChuMicro library table](https://github.com/ChuMicro/ChuMicro#the-libraries), and install experimental counterparts of every library in use. Leave all other `chumicro-*` packages installed, including `chumicro-workspace`, `chumicro-deploy`, and `chumicro-repl`.

For timing, the replacement is:

```bash
pip uninstall -y chumicro-timing
pip install chumicro-timing-experimental
```

<span id="troubleshooting"></span>

## Troubleshooting installs

Check names against [Names and channels](#names-and-channels) and the [ChuMicro library table](https://github.com/ChuMicro/ChuMicro#the-libraries). Linked workbench CLI instructions apply only to workbench readers.

- **`library add` ends with `(kind: package-not-found)`:** Check spelling and underscores. Retry with the corrected name; if the library is experimental-only, use the same command plus `--channel experimental`.
- **`Deploy refused: unresolved import.`**, or plural `imports`: Check the importing file and unresolved name shown, correct spelling, ensure `library add` succeeded, and retry. For deeper causes, see [Deploy refused, or ImportError on boot](troubleshooting/deploy-refused-importerror.md).
- **CIRCUITPY absent or `Could not find a connected CircuitPython device.`:** If mounted, use `circup --path <folder> install chumicro_timing`. Otherwise check the data cable and connection using [Board not found](troubleshooting/board-not-found.md). For macOS mounts, see [macOS CIRCUITPY deploy troubleshooting](troubleshooting/macos-circuitpy.md). Wrong or absent firmware needs the [Board support](#board-support) downloads. C3/C6 may need the [drive-less route](#circuitpython-with-circup).
- **`WARNING:` and `<name> is not a known CircuitPython library.`:** Check spelling and unwanted hyphens. Inspect `circup bundle-show`; if stable is absent, run `circup bundle-add ChuMicro/ChuMicro-Bundle`. For an experimental-only library, follow the [CircuitPython route’s experimental ending](#circuitpython-with-circup).
- **`mpremote: no device found`:** Check the data cable, USB connection, and competing serial monitors. Use the cable/port checks in [Board not found](troubleshooting/board-not-found.md).
- **`<reason> requesting <url>`:** Check the laptop’s network connection.
- **`Package not found: github:.../package.json`:** Check the name. If experimental-only, use the [MicroPython route’s experimental ending](#micropython-with-mpremote).
- **pip reports `No matching distribution found`:** Check table spelling and the environment’s Python version, which must be 3.11 or later. If experimental-only, use the [CPython experimental name](#cpython-with-pip); otherwise fix the name or Python version.
- **`error: externally-managed-environment`:** Activate a virtual environment. For circup or mpremote, pipx is another option.
- **Board `ImportError` after workbench deploy:** Check chip and firmware support, then [Deploy refused, or ImportError on boot](troubleshooting/deploy-refused-importerror.md).
- **Board `ImportError` after circup/mip:** Check files under `CIRCUITPY/lib` or the printed MicroPython target, plus chip and firmware support. For mixed MicroPython forms, follow cleanup and reinstall one form without changing channel.
- **Import-time `MemoryError`:** For MicroPython source installs, follow the form-change cleanup procedure and install bytecode. For further causes, see [Running out of memory](troubleshooting/out-of-memory.md).
- **Other symptoms:** See [Troubleshooting](troubleshooting/README.md).
