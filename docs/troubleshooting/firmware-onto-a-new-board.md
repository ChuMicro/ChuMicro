# Getting firmware onto a new board

ChuMicro drives boards that already run CircuitPython or MicroPython, the two Python runtimes it targets.  A board fresh from a vendor may arrive blank, carry some other firmware, or run a Python version too old for the libraries, and each shows up differently.  This page covers flashing a runtime onto a new board and the board-specific snags you hit while doing it.

## `NO_PYTHON_RUNTIME`: "no firmware detected"

The board isn't running a Python runtime.  A fresh or blank board, or one shipped with Arduino or other firmware, mounts as a UF2 mass-storage drive (a USB drive named `RPI-RP2` holding an `INFO_UF2.TXT` file) instead of opening a serial port, or it opens a port where `probe` just hangs.

Flash a runtime.  Flashing erases whatever is on the board.

- RP2040 and RP2350 boards use the UF2 method.  Put the board in its bootloader first by holding BOOTSEL (or double-tapping RESET on many boards) while plugging in, so its UF2 drive mounts:

```bash
chumicro-workspace install-firmware --method uf2 --device <id>
```

- ESP32-family boards flash over serial with esptool (the ESP32 flashing tool).  Add `--erase` on a first flash or when switching runtimes:

```bash
chumicro-workspace install-firmware --method esptool --erase --device <id>
```

For a board not yet in `devices.yml`, pass the image URL with `--url <firmware-url>` in place of `--device`.

## A new board registers fine, then hits missing-module errors at deploy

Vendors often ship boards with old firmware, sometimes well below the version ChuMicro supports (the floors are MicroPython 1.27 and CircuitPython 10.1).  The board runs, but library imports and API calls the older runtime lacks fail in confusing ways at deploy time.  (background: [Decision 0039](../../plans/decisions/0039-firmware-version-floor.md))

`add-device` prints an `OLD` warning naming the floor and the running version when you register a board below it.  Upgrade the firmware before troubleshooting anything else:

```bash
chumicro-workspace install-firmware --method uf2 --device <id>
```

## ESP32-S2 goes silent entering the bootloader; esptool reports "No serial data received"

On MicroPython, an ESP32-S2 told to enter its ROM bootloader drops into download mode at the silicon level but never brings its USB serial connection back up.  No new port appears in the poll, and esptool's auto-reset can't reach it, so the flash fails.  (CircuitPython handles the S2 correctly.)  The original port stays listed but unresponsive.

Put the board into its bootloader by hand: hold BOOT (GPIO0), press and release RESET, then release BOOT.  The flashing tool keeps a manual-entry prompt for this case, so you can run the button sequence and continue from there.

## `reset-board` erased my `settings.toml` and `boot.py`

`reset-board` reformats the board's user filesystem to a clean slate.  It is the wipe path, separate from reflashing firmware, and it removes every user file, including a hand-edited `settings.toml` (the CircuitPython config file) and `boot.py`.

The command refuses to run without `--yes`, which is the moment to stop and reconsider.  Back up any board-only files first, then:

```bash
chumicro-workspace reset-board --device <id> --yes
```

It is a no-op in RAM or mount mode, where there is no device filesystem to wipe.
