---
title: "Start here: from a new board to your code running on it"
---

# Start here

This page goes from a board still in its packaging to your own code running on it, on your own wifi. It takes about fifteen minutes, and every command runs on your laptop.

You need a board (an ESP32 or a Raspberry Pi Pico W are the usual starting points), a USB cable that carries data rather than only power, and Python 3.11 or newer on your laptop.

## 1. Get the workbench

The [workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template) is a whole project you copy. It holds your code, keeps track of your boards, deploys to them, and runs your tests. Press **Use this template** on that page to make your own copy on GitHub, then clone it. Or copy it straight down and start a fresh history:

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
rm -rf .git && git init          # the history is yours from here
python3 run.py setup             # creates a virtual environment, installs the tooling
```

`run.py` is a wrapper that re-executes inside the workspace's virtual environment, so `python3 run.py <command>` works from a clean shell without activating anything first.

## 2. Put a runtime on the board

A new board usually arrives without CircuitPython or MicroPython on it. Plug it in and let the workbench install one:

```bash
python3 run.py install-firmware
```

This handles both styles of board: the ones that expose a drive you drop a UF2 file onto (Pico and friends) and the ones that need esptool over serial (ESP32 and friends). It asks which runtime you want and fetches the right build for your board. Pass `--help` for the flags, including `--runtime`, `--method`, and `--url` if you want to point it at a specific firmware file.

If your board already runs CircuitPython or MicroPython, skip this step.

## 3. Register the board

```bash
python3 run.py bootstrap
```

This asks which serial port your board is on, works out which runtime it is running, and writes it into `devices.yml` so later commands know what "the board" means. From now on you can name it, or leave it out and get the active one.

Two things that go wrong here have their own pages: [the board does not appear](troubleshooting/board-not-found.md), and on a Mac, [CIRCUITPY not mounting](troubleshooting/macos-circuitpy.md).

## 4. Make a project and send it over

```bash
python3 run.py new blinker      # scaffolds projects/blinker/
python3 run.py deploy blinker   # copies it to the board and runs it
```

Your code lives on your laptop under version control and gets copied to the board when you ask. Editing straight onto a CIRCUITPY drive wears the flash out and loses work when the cable moves; this way the board holds a copy and your laptop holds the original.

Deploys write to flash and verify every file by checksum. While you are iterating you can switch a board to RAM deploys, which write nothing to flash at all.

To watch what the board prints:

```bash
python3 run.py deploy blinker --tail 30    # ship it, then watch for 30 seconds
python3 run.py repl                        # or open an interactive REPL
```

## 5. Add a library

Say the project needs wifi:

```bash
python3 run.py library add chumicro_wifi
python3 run.py deploy blinker
```

The library lands in the workspace, and the deploy carries it to the board along with your code. [Installing libraries](install.md) covers doing this outside a workspace, using circup, mip, or pip directly.

## 6. Give it your wifi password

Network examples read your wifi name and password from `secrets.toml` in the workspace root, which is gitignored. The deploy bakes it onto the board, so credentials stay out of your code and out of your git history.

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

[Wiring wifi credentials](wiring-wifi-credentials.md) covers the details, including boards with more than one network to try.

## Where to go next

- [Questions people ask](faq.md): why a board freezes on the network, whether these libraries use async, what they cost in flash, and how to test without hardware.
- [The library reference](https://chumicro.com/ChuMicro/): every library, with its own guide and API pages.
- [Troubleshooting](troubleshooting/README.md): keyed to the symptom you are looking at.
- The template's own README walks a full reference project: a wifi-to-MQTT sensor node with a boot counter that survives a power cut, and the flow for more than one board.
