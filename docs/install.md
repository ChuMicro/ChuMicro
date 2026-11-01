---
title: "Installing ChuMicro libraries on CircuitPython, MicroPython, and CPython"
---

# Installing ChuMicro libraries

Every ChuMicro library installs by name, with the tool your runtime already uses.  Swap `timing` in each command for the library you need.

Your board needs CircuitPython 10.1 or newer, or MicroPython 1.27 or newer.  [Start here](start-here.md#1-put-circuitpython-or-micropython-on-the-board) installs one on a board that has neither.

> pip names use hyphens, as in `chumicro-timing`.  Everything on the board uses underscores, as in `chumicro_timing`, because a Python import name cannot contain a hyphen.  Copy the commands below as written.

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

Each library's README carries its own install line.

## Check it worked

Save this as `code.py` on the CIRCUITPY drive:

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

The board's LED switches on or off every half second until you unplug it.

On MicroPython, change the LED lines as [On MicroPython](coming-from-arduino.md#on-micropython) shows.  Copy the file to the board as `main.py` with `mpremote cp blink.py :main.py`, then press reset to start it.

[Coming from Arduino](coming-from-arduino.md) explains why the loop has no `time.sleep()` in it.

## CircuitPython: circup and the ChuMicro bundle

[circup](https://github.com/adafruit/circup) is CircuitPython's package manager.  It finds third-party packages through [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands).  Register the ChuMicro bundle once, then install any library by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro_timing
```

A bundle registered once serves every project on that computer.

## MicroPython: mip

[mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html) is MicroPython's command-line tool, installed with `pip install mpremote`.  It runs mip, MicroPython's package manager, against a board over USB:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

A board already on your WiFi can install from its own prompt:

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

CPython is the Python your laptop runs.  A library installed there runs your board code's tests on the laptop:

```bash
pip install chumicro-timing
```

pip also installs the laptop tools: `chumicro-workspace`, `chumicro-deploy`, `chumicro-repl`, and `chumicro-pytest-device`.

## Experimental (pre-release) channel

A library's pre-release build publishes each time its `VERSION` changes on `main`.  New work reaches this channel first and can break between releases.

> **Register one bundle per computer.**  With both bundles registered, circup picks either version of a package.

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

A project that grows past one file fits the [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template).  `python3 run.py library add chumicro_timing` fetches a library once for every project in the workspace.  `python3 run.py deploy <project>` copies a project and the libraries it imports onto the board.  [Start here](start-here.md) walks through both commands.

`library add --channel experimental` pulls from the experimental channel.

A workspace deploy makes the board's files match the project, so it removes libraries installed by hand with circup or mip.  [Deploys and file persistence](troubleshooting/deploys-and-file-persistence.md) lists what a deploy keeps.

## Board support

ChuMicro runs on boards with at least 256 KB of RAM and 2 MB of flash, about 800 KB of which is free for your files.  These boards have run the libraries on a test bench:

- Raspberry Pi Pico W (RP2040), under CircuitPython and under MicroPython.
- ESP32 boards from the classic, S2, and S3 families.

ESP32-C3, ESP32-C6, and RP2350 are supported chip families that have had no bench time yet.  Every library also runs on CPython on your laptop, for testing.

Each library README's "Platform support" section lists that library's per-board limits.

## Troubleshooting

- **No CIRCUITPY drive appears, or circup finds no board.**  A board without CircuitPython shows no CIRCUITPY drive.  [Start here](start-here.md#1-put-circuitpython-or-micropython-on-the-board) installs it.  [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md) covers boards that will not take a flash.
- **`circup install` says a library is `not a known CircuitPython library`.**  A hyphenated name causes this most often.  circup installs by the on-device package name, which uses underscores: `circup install chumicro_timing`.  With an underscored name, the bundle is the next suspect.  Register it once with `circup bundle-add ChuMicro/ChuMicro-Bundle`.
- **`mip.install()` at the board's prompt hangs.**  That form downloads from GitHub over the board's own WiFi, so the board has to be online first.  `mpremote mip install` downloads on your laptop and copies the files over USB.
- **`pip install` says "no matching distribution found".**  Check the spelling against the [library table](https://github.com/ChuMicro/ChuMicro#the-libraries).  A library merged since the last stable release exists only on the experimental channel, as `chumicro-<name>-experimental`, until its first stable release.
- **`ImportError` after install on a board.**  Check that the files landed: `mpremote ls :lib` on MicroPython, or `lib/chumicro_timing/` on the CIRCUITPY drive.  circup and mip can leave a partial install without reporting an error.

[Troubleshooting](troubleshooting/README.md) covers board, firmware, WiFi, TLS, and memory problems, starting from the symptom.
