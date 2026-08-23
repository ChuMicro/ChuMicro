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
