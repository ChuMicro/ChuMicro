---
title: "Installing ChuMicro libraries on CircuitPython, MicroPython, and CPython"
---

# Installing ChuMicro libraries

Every ChuMicro library installs the same way, by name, with the tool your runtime already uses.  Pick the method for your runtime and swap `timing` for whichever library you need.

Your board needs CircuitPython 10.1 or newer, or MicroPython 1.27 or newer.  A brand-new board may have neither; [Start here](start-here.md) installs a runtime before anything else.

> **A note on naming:** pip names use hyphens (`chumicro-timing`), and everything on the board uses underscores (`chumicro_timing`), because a Python import name cannot contain a hyphen.  Copy the commands below as written.

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

## Check it worked

Save this as `code.py` on the CIRCUITPY drive.  The board's LED switches on or off every half second and keeps going until you unplug it:

```python
import board, digitalio
from chumicro_timing import Rate, ticks_ms

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
blink = Rate(500, ticks_ms())       # due every 500 ms

while True:
    now = ticks_ms()
    if blink.due(now):              # is it time yet?
        led.value = not led.value
```

On MicroPython, swap `import board, digitalio` for `from machine import Pin`, set the LED up with `led = Pin("LED", Pin.OUT)` on a Pico W (or `Pin(2, Pin.OUT)` on most ESP32 boards), flip it with `led.value(not led.value())`, and copy the file over as `main.py` with `mpremote cp blink.py :main.py`.  Press reset to start it.

The loop has no `time.sleep()` in it, so anything else you add gets a turn on every pass.  [Coming from Arduino](coming-from-arduino.md) explains why that matters once a board has more than one job.

## CircuitPython: circup and the ChuMicro bundle

[circup](https://github.com/adafruit/circup) is CircuitPython's package manager.  It finds third-party packages through [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands).  Register the ChuMicro bundle once, then install any library by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro_timing
```

Bundle registration is per-machine, not per-project.  Add it once on a laptop and every workspace on that laptop sees it.

## MicroPython: mip

[mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) is MicroPython's command-line tool (`pip install mpremote`); mip is its package manager, which mpremote drives here:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

Or from the board's own prompt, on a board that is already on your WiFi:

```python
import mip
mip.install("github:ChuMicro/ChuMicro-Bundle/chumicro_timing")
```

### Pre-compiled `.mpy` bytecode

Add `mpy6/` before the package name for faster startup and lower RAM use.  These packages load on MicroPython 1.27 and newer:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
```

## CPython: pip

```bash
pip install chumicro-timing
```

CPython is the Python your laptop runs.  No bundle, no `.mpy` step, just pip.  Install a library there to test board code on your laptop, and for the workbench tools (`chumicro-deploy`, `chumicro-repl`, `chumicro-workspace`, `chumicro-pytest-device`).

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

Once a project grows past one file, the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) is the easier way to install.  Your code lives on your laptop, and `python3 run.py library add chumicro_timing` fetches a library once for every project in the folder.  `python3 run.py deploy <project>` then copies your project and the libraries it imports onto the board and checks each file arrived intact, so you stop editing files live on the CIRCUITPY drive.  [Start here](start-here.md) walks through it.

`library add` pulls from the stable channel unless you pass `--channel experimental`.

## Board support

ChuMicro libraries run on:

- **CircuitPython**: ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico, Pico W), and most boards with at least 256 KB RAM and 2 MB physical / ~800 KB usable flash.
- **MicroPython**: the same hardware classes, plus broader STM32 / ESP-IDF coverage.
- **CPython**: your laptop, for testing.

A few libraries have per-board restrictions.  Each library README's "Platform support" section flags them.

## Troubleshooting

- **No CIRCUITPY drive appears, or circup finds no board.**  The board may not be running CircuitPython yet.  Install it from [circuitpython.org/downloads](https://circuitpython.org/downloads) by following the steps on your board's page; [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md) covers boards that will not take a flash.
- **`circup install` says a library is `not a known CircuitPython library`.**  Most often the name is hyphenated.  circup installs by the on-device package name, which uses underscores: run `circup install chumicro_timing`, not `chumicro-timing`.  If the name is already underscored, you may not have registered the bundle yet: run `circup bundle-add ChuMicro/ChuMicro-Bundle` once.
- **`mip.install()` at the board's prompt hangs.**  That form downloads from GitHub over the board's own WiFi, so the board has to be online first.  `mpremote mip install` from your laptop downloads on the laptop and copies the files over USB instead.
- **`pip install` says "no matching distribution found".**  Check the spelling against the library table in the [README](https://github.com/ChuMicro/ChuMicro#the-libraries).  Every library has a stable release, so a correctly spelled name resolves; the exception is a library merged since the last stable promotion, which is on the experimental channel only until it is promoted (`pip install chumicro-timing-experimental`).
- **`ImportError` after install on a board.**  Check that the files landed: `mpremote ls :lib` on MicroPython, or look for `lib/chumicro_timing/` on the CIRCUITPY drive.  circup and mip don't always report a partial install.

For anything beyond install problems (board not found, firmware, WiFi, TLS, memory), [Troubleshooting](troubleshooting/README.md) starts from the symptom and walks to the fix.
