# Hardware and tooling traps

## CIRCUITPY mount state

Leave the mount alone from the host. No `diskutil unmount`, `eject`, `mount`, or `rm /Volumes/CIRCUITPY*`. Deploy and transport own the mount, and interference defeats the EACCES classifier. Destructive remediation is `chumicro-workspace reset-board --yes`.

## Writing to /Volumes/CIRCUITPY by hand

`cp -r` included. The board auto-reloads the moment the drive changes, so board and host rewrite the same filesystem at once, and on macOS `cp` drops `._` AppleDouble files into the directories being written. FAT directory entries tear under that: the host can list them, `stat` returns EINVAL, nothing can unlink them, and every later deploy fails until `reset-board --yes` reformats.

Deploy through `test-libraries-functional` or `chumicro-workspace deploy`, which quiesce the board first.

## Driving ESP32-family GPIOs as outputs

The functional suites drive pins as outputs to raise their own edges, and on ESP32-family chips some GPIO numbers are wired to the chip's own storage: 6 to 11 are SPI flash on a classic ESP32, 26 to 32 are flash and PSRAM on the S2 and S3, 16 and 17 are PSRAM on a WROVER or a TinyPICO, and 19 and 20 are native USB on both S-series parts. Driving one does not raise, it resets the board. 0, 2, 12, 15, 45 and 46 are strapping pins: fine to read, but a level held on one through a reset changes how the chip boots. GPIO 34 to 39 on a classic ESP32 are input-only with no pull-ups. rp2040 has none of these reservations; any GP pin reads and drives. The suites' `_CANDIDATES` tuples (5, 4, 13, 14, 18) are the numbers clean on every family at once.

## Two CircuitPython boards at once

They mount as `/Volumes/CIRCUITPY` and `/Volumes/CIRCUITPY 1`. That is normal disambiguation, not a wedge; check `chumicro-workspace devices` first. Parallel deploys to two CircuitPython boards race for the mount, so run them one at a time.

## IDE config files

`cd` to the main checkout before editing `.iml`, `.idea/`, `pyrightconfig.json`, or `.vscode/settings.json`. `sync-ide` run from a worktree writes paths that break in main. PyCharm also rewrites `.idea/chumicro.iml` on its own; `python scripts/run.py sync-ide` restores the managed layout.

## replace_all is a literal substring swap

Before renaming a short identifier like `_foo`, grep for longer names containing it (`_apply_foo`).

## PCF8574 LCD backpacks without pull-ups

Many LCM1602-class backpacks leave the SDA and SCL pull-ups unpopulated, and the two runtimes then fail differently on the same board. MicroPython's `machine.I2C` enables the rp2040's internal pull-ups on construction (`ports/rp2/machine_i2c.c`), which carry the bus below 200 kHz and fail every write at the port's 400 kHz default: on a Pi Pico W a 50-write loop to a backpack at 0x27 measured 0/50 at 400 kHz, 50/50 at 200 kHz, and 50/50 at 100 kHz. CircuitPython's `busio.I2C` raises `RuntimeError: No pull up found on SDA or SCL` and never constructs; its check drives both lines low with the internal pull-downs, releases every pull, and requires the line back high within 3 us (`ports/raspberrypi/common-hal/busio/I2C.c`), so internal pull-ups cannot satisfy it by design.

To tell whether external pull-ups are present, read the pins with the internal pull-down engaged. `Pin(4, Pin.IN, Pin.PULL_DOWN)` reading 0 means nothing stronger holds the line; a 4.7 kOhm pull-up reads 1. Adding 4.7 kOhm from each line to 3V3 took the same board to 50/50 at 400 kHz and let CircuitPython construct.

## An I2C scan passes on a bus that cannot write

`scan()` is not evidence the bus works. The rp2040 I2C block does not support zero-length writes, so both runtimes bit-bang them: MicroPython builds a temporary `SoftI2C` (`ports/rp2/machine_i2c.c`), CircuitPython keeps a `bitbangio.I2C` beside the hardware peripheral (`ports/raspberrypi/common-hal/busio/I2C.c`). The bit-banged path clocks slower than the hardware path, so a marginal bus answers a scan and then fails every real transfer. Confirm with a `writeto` loop.

## displayio holds pins across a soft reload

A display registered by an earlier deploy still owns its pins after the next deploy's soft reboot, because the clean slate wipes the filesystem and not the board's RAM. A GC9A01A example wired chip-select to GP5 on a Pi Pico W, and the next charlcd deploy to that board raised `ValueError: GP5 in use` from `busio.I2C(board.GP5, board.GP4)`. `displayio.release_displays()` frees the pins, and so does a power cycle.

## Auto-reload off makes a REPL tail look dead

A CircuitPython board reporting `Auto-reload is off.` does not re-run `code.py` when the host writes to CIRCUITPY, so `chumicro-repl --tail` attaches to a finished program and captures nothing. Send Ctrl-D over the serial port to soft reboot and produce output.
