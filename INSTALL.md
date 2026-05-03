# Installing ChuMicro libraries

Every ChuMicro library installs the same way.  Pick the install method for your runtime, swap `chumicro-timing` for whichever library you need.

> **A note on naming:** pip uses hyphens (`chumicro-timing`); the import name and bundle path use underscores (`chumicro_timing`).  That's standard across the Python ecosystem — PyPI uses hyphens by convention, but Python import names must be valid identifiers.  Copy commands from the blocks below as-is.

## Quick install (stable channel)

```bash
# CircuitPython (via circup)
circup bundle-add ChuMicro/ChuMicro-Bundle    # one-time, registers the bundle
circup install chumicro-timing                # then install any library by name

# MicroPython (via mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython (via pip)
pip install chumicro-timing
```

The browse-and-pick experience: each library's README has its own install line; once the bundle is registered, every library is one command away.

## CircuitPython — circup + the ChuMicro bundle

[circup](https://github.com/adafruit/circup) is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages.  Register the ChuMicro bundle once, then install any library by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

Bundle registration is per-machine, not per-project — once you've added it on a laptop, every workspace on that laptop sees it.

## MicroPython — mip

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

Or from the REPL on a network-capable board:

```python
import mip
mip.install("github:ChuMicro/ChuMicro-Bundle/chumicro_timing")
```

### Pre-compiled `.mpy` bytecode

Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
```

## CPython — pip

```bash
pip install chumicro-timing
```

CPython is what your laptop runs.  No bundle, no `.mpy` step — just pip.  Useful for host-side testing of code that targets a board, and for the workbench tools (`chumicro-deploy`, `chumicro-repl`, `chumicro-workspace`, `chumicro-pytest-device`).

## Experimental (pre-release) channel

Pre-release builds publish automatically when a library `VERSION` bumps.  They're the bleeding edge of `main`.

> **Don't register both bundles simultaneously** — circup may pick either version for a given package.  Pick one channel per laptop.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-timing

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

For a real project — multiple libraries, deploy automation, no live-on-device editing of fragile CIRCUITPY drives — use the [ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template).  `python3 run.py setup` self-bootstraps the venv and installs the workspace tooling; `python run.py new my_project` scaffolds a project from the template; `python run.py deploy my_project` ships it to your board safely (atomic flash mode by default — no half-written files when something goes wrong, no FAT-filesystem wear from save-on-every-keystroke).

Recommended even for a single-project board.

## Board support

ChuMicro libraries run on:

- **CircuitPython** — ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico, Pico W), and most boards with at least 256 KB RAM and 4 MB flash.
- **MicroPython** — same hardware classes, plus broader STM32 / ESP-IDF coverage.
- **CPython** — your laptop, for testing.

Some libraries have per-board notes (e.g. `chumicro-http-server` doesn't support TLS-server on CircuitPython-on-rp2 — use ESP32 or MicroPython for that combo).  Each library README's "Platform support" section flags any restrictions.

## Troubleshooting

- **`circup install` says the package isn't in any bundle** — you haven't run `circup bundle-add ChuMicro/ChuMicro-Bundle` yet.  Bundle registration is per-machine; do it once.
- **`mpremote mip install` hangs** — the board needs network connectivity (mip downloads from GitHub through the device's wifi).  Either bring wifi up first, or download the package on your laptop and `mpremote cp` it manually.
- **`pip install` says "no matching distribution found"** — the package may not have published a stable release yet (most ChuMicro libraries are pre-1.0 and experimental).  Try the experimental package name (`chumicro-timing-experimental`).
- **`ImportError` after install on a board** — verify the file actually landed: `mpremote ls /lib/` (MP) or check `/lib/chumicro_timing/` on the CIRCUITPY drive (CP).  circup / mip don't always report partial installs cleanly.
