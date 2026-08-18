---
title: "Installing ChuMicro libraries on CircuitPython, MicroPython, and CPython"
---

# Installing ChuMicro libraries

Every ChuMicro library installs the same way.  Pick the method for your runtime and swap `chumicro-timing` for whichever library you need.

These commands assume your board already runs CircuitPython or MicroPython.  A brand-new board may not: [Start here](https://chumicro.com/ChuMicro/guides/start-here/) flashes a runtime before anything else.

> **A note on naming:** pip uses hyphens (`chumicro-timing`); the import name and bundle path use underscores (`chumicro_timing`).  That's standard across the Python ecosystem.  PyPI names use hyphens by convention, and Python import names must be valid identifiers.  Copy commands from the blocks below as-is.

## Quick install (stable channel)

```bash
# CircuitPython (via circup)
circup bundle-add ChuMicro/ChuMicro-Bundle    # one-time, registers the bundle
circup install chumicro_timing                # then install any library by name

# MicroPython (via mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython (via pip)
pip install chumicro-timing
```

Each library's README carries its own install line, so once the bundle is registered, any library is one command away.

## CircuitPython: circup and the ChuMicro bundle

[circup](https://github.com/adafruit/circup) is CircuitPython's package manager.  It finds third-party packages through [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands).  Register the ChuMicro bundle once, then install any library by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro_timing
```

Bundle registration is per-machine, not per-project.  Add it once on a laptop and every workspace on that laptop sees it.

## MicroPython: mip

[mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) is MicroPython's command-line tool (`pip install mpremote`); mip is its on-board package manager, which mpremote drives here:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

Or from the REPL on a network-capable board:

```python
import mip
mip.install("github:ChuMicro/ChuMicro-Bundle/chumicro_timing")
```

### Pre-compiled `.mpy` bytecode

Add `mpy6/` before the package name for faster startup and lower RAM use on boards with mpy format v6 (MicroPython 1.24+):

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
```

## CPython: pip

```bash
pip install chumicro-timing
```

CPython is what your laptop runs.  No bundle, no `.mpy` step, just pip.  Useful for host-side testing of code that targets a board, and for the workbench tools (`chumicro-deploy`, `chumicro-repl`, `chumicro-workspace`, `chumicro-pytest-device`).

## Experimental (pre-release) channel

Pre-release builds publish automatically whenever a library's `VERSION` bumps on `main`.  New work lands there first, and things can break between releases.

> **Don't register both bundles at once.**  circup may pick either version for a given package.  Pick one channel per laptop.

```bash
# CircuitPython: switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro_timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing

# CPython
pip install chumicro-timing-experimental
```

| Channel | Bundle repo | Source |
|---|---|---|
| **Stable** | [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) | tagged releases |
| **Experimental** | [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental) | `main` |

## Project workspaces

For a real project (multiple libraries, deploy automation, no live editing on a fragile CIRCUITPY drive), use the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template).  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) walks through creating one.  From inside a clone of that template, `python3 run.py setup` bootstraps the virtual environment and installs the tooling; `python3 run.py new my_project` scaffolds a project; `python3 run.py deploy my_project` ships it to your board with verified flash deploys by default (rsync plus a post-write checksum, and no filesystem wear from save-on-every-keystroke editing).

Those `python3 run.py <cmd>` forms only work inside a cloned workspace template, where `run.py` is a bootstrap wrapper that re-executes in the workspace's virtual environment and dispatches to `chumicro-workspace`.  Once that environment is active, `chumicro-workspace <cmd>` runs the same commands directly.  Libraries come in through `chumicro-workspace library add chumicro_timing`, which pulls from the stable channel unless you pass `--channel experimental`.

Recommended even for a single project on a single board.

## Board support

ChuMicro libraries run on:

- **CircuitPython**: ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico, Pico W), and most boards with at least 256 KB RAM and 2 MB physical / ~800 KB usable flash.
- **MicroPython**: the same hardware classes, plus broader STM32 / ESP-IDF coverage.
- **CPython**: your laptop, for testing.

A few libraries have per-board restrictions.  Each library README's "Platform support" section flags them.

## Troubleshooting

- **No CIRCUITPY drive appears, or circup finds no board.**  The board may not be running CircuitPython yet.  Flash a runtime first: [Start here](https://chumicro.com/ChuMicro/guides/start-here/) walks through it, and `chumicro-deploy flash-firmware --help` covers the flags.
- **`circup install` says a library is `not a known CircuitPython library`.**  Most often the name is hyphenated.  circup installs by the on-device package name, which uses underscores: run `circup install chumicro_timing`, not `chumicro-timing`.  If the name is already underscored, you may not have registered the bundle yet: run `circup bundle-add ChuMicro/ChuMicro-Bundle` once (registration is per-machine, so do it once).
- **`mpremote mip install` hangs.**  The board needs network connectivity; mip downloads from GitHub through the device's wifi.  Bring wifi up first, or download the package on your laptop and `mpremote cp` it over.
- **`pip install` says "no matching distribution found".**  Check the spelling against the library table in the [README](https://github.com/ChuMicro/ChuMicro#libraries).  Every library has a stable release, so a correctly spelled name resolves; the exception is a library merged since the last stable promotion, which is on the experimental channel only until it is promoted (`pip install chumicro-timing-experimental`).
- **`ImportError` after install on a board.**  Verify the files actually landed: `mpremote ls /lib/` on MicroPython, or look for `/lib/chumicro_timing/` on the CIRCUITPY drive.  circup and mip don't always report partial installs cleanly.

For anything beyond install problems (board not found, firmware, WiFi, TLS, memory), [Troubleshooting](https://chumicro.com/ChuMicro/guides/troubleshooting/) starts from the symptom and walks to the fix.
