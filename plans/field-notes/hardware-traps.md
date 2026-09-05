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

## displayio's background refresh stalls the app loop

Background refresh is free to the library, not to the loop.  displayio
repaints from C without an app-side flush, so `ScreenService` has nothing
to do on CircuitPython, but the repaint runs in the VM's background-task
hook and user code does not advance while a transfer is on the bus.

Measured on a LOLIN S2 Mini under CircuitPython 10.2.0, an SSD1306 128x64
over I2C, timing 3000 passes of a fixed loop body that dirties one pixel
each pass:

| Bus | mean | p99 | steady-state max | passes over 5 ms |
|---|---|---|---|---|
| 100 kHz | 0.93 ms | 5.46 ms | 29.8 ms | 112 / 3000 |
| 400 kHz | 0.78 ms | 2.75 ms | 11.4 ms | 19 / 3000 |

The first round's max is larger again, 111.8 ms at 100 kHz and 40.5 ms at
400 kHz, which is the initial full-screen repaint after `root_group` is
assigned; later rounds settle to the numbers above.  With the bitmap left
unmutated the tail disappears entirely (max 2.3 ms), so the cost tracks
dirty regions rather than the display merely existing.

Two consequences.  A 5 ms tick budget is exceeded on roughly 0.6 % of
passes at 400 kHz and 3.7 % at 100 kHz, so a CircuitPython app driving a
display cannot assume the budget holds.  And bus frequency is the lever:
four times the clock cut the steady-state worst case by 2.6x.

The same probe on a Pi Pico W under CircuitPython 10.2.1 with a GC9A01A
240x240 round TFT over SPI at 40 MHz (`.scratch/probe_cp_gc9a01a_jitter.py`,
a 2-color full-screen bitmap plus a 16x16 notch on its own palette;
the loop body alone costs 2.55 ms on this RP2040):

| Case | mean | p99 | max | passes over 5 ms |
|---|---|---|---|---|
| auto refresh, one pixel per pass, steady | 2.75 ms | 3.5 ms | 6.4 ms | 9 to 15 / 3000 |
| auto refresh, first round | 2.86 ms | 3.5 ms | 338.6 ms | 10 / 3000 |
| auto refresh, 16x16 notch per pass | 2.85 ms | 4.6 ms | 7.4 ms | 4 / 3000 |
| `refresh()`, one dirty pixel | 0.37 ms | 0.79 ms | 0.95 ms | 0 / 200 |
| `refresh()`, 16x16 notch | 1.70 ms | 2.23 ms | 2.53 ms | 0 / 200 |
| `refresh()`, full screen | 318 ms | 318.5 ms | 318.5 ms | 20 / 20 |

The cost tracks the dirty area, not the bus: 115,200 bytes cross a
40 MHz bus in about 23 ms, and the full-screen repaint takes 318 ms,
about 5.5 us per pixel in the firmware's color converter on the RP2040
(the 16x16 notch at 1.7 ms is 6.6 us per pixel, the same slope plus a
fixed cost).  A whole-frame change on this board therefore stalls the
loop for a third of a second whether the refresh is automatic or called
from a handler, while the MicroPython indexed driver on the same board
moves a whole frame in 124 ms spread over strips of at most 3.4 ms.

Chunking the frame through displayio does not change the slope.  With a
shadow bitmap and a displayed bitmap of the same size, copying one
rectangle of about 480 pixels per advance with `bitmaptools.blit` and
calling `display.refresh()` so exactly that rectangle is dirty
(`.scratch/probe_cp_paths.py`, part 1, 16 colors), every chunk shape
costs the same: 4.1 ms mean, 4.6 to 5.5 ms worst, 507 to 520 ms for a
whole frame, and the two bitmaps take 57.7 KB.  Each refresh call carries
about 1.5 ms of fixed cost on top of the per-pixel slope, so the shape
of the chunk is irrelevant and the tick budget admits about 480 pixels
per refresh on this chip.  Colors per pixel do not matter either: 256 and
16 colors measure the same slope.

Bypassing displayio's pipeline does.  A `displayio.Bitmap(240, 240, 65536)`
drawn with `bitmaptools` in the panel's RGB565 byte order exposes its
buffer as 16-bit items, and `busio.SPI.write(view, start=, end=)` streams
a strip of it straight to the panel after the same window commands the
MicroPython driver sends (`.scratch/probe_cp_direct.py`, panel brought up
by hand over `busio.SPI` and `digitalio`):

| Strip | mean | worst | frame |
|---|---|---|---|
| 6 rows | 1.49 ms | 1.89 ms | 64.5 ms |
| 10 rows | 2.06 ms | 2.50 ms | 52.6 ms |
| 20 rows | 3.56 ms | 3.94 ms | 44.3 ms |

The frame takes 116,784 bytes of the 174,176 free on a fresh Pico W
heap, and the card it drew read right on the panel.  That is the fastest
whole-frame path measured on this board under either runtime, because
the bus is the only cost.  The probe's 100 bytes of allocation per strip
is its own `time.monotonic_ns()` integers; a driver with pre-sliced views
has none.  After a displayio session had churned the heap, the same
115,200-byte allocation failed, so the frame has to be allocated first.

## CircuitPython board builds lack the two-argument next()

`next(iterator, default)` works on the CircuitPython unix port and on
MicroPython, so the port suites pass, and a Pi Pico W under CircuitPython
10.2.1 raised `TypeError: function takes 1 positional arguments but 2
were given` from the same line the first time `gc9a01a_counter.py`
advanced a flush.  `chumicro_screens.core` now tries
`next(iter(()), None)` at import and falls back to catching
`StopIteration`, which costs one 96-byte exception object per finished
frame on the board and nothing on the other runtimes.
