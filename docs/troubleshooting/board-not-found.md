# Board not found

When a board is plugged in but the deploy or REPL tools can't reach it, the cause is almost always the cable, the port, or which program is holding it, not the board itself.  This page covers the ways a board goes missing from `python3 run.py discover` and the serial-port errors you hit before any code reaches the device, in the order a first-week user tends to meet them.  The macOS-only failures around the CIRCUITPY drive (the USB drive a CircuitPython board mounts) are covered separately in [macOS CIRCUITPY deploy troubleshooting](macos-circuitpy.md).

## The board never shows up in `python3 run.py discover`

A charge-only USB cable carries power but no data, so the board runs while never enumerating as a serial port.  A board sitting in its UF2 bootloader (a firmware-flashing mode where it mounts as a USB drive instead of a serial port) or a port that macOS dropped after an unclean unplug produces the same empty list.

- Swap to a known-good data cable and replug.  Plenty of cheap cables are charge-only.
- Look for a mass-storage drive named `RPI-RP2` (or a similar `<BOARD>BOOT` volume).  If one is mounted, the board is in its bootloader with no runtime, so flash firmware first (see [Getting firmware onto a new board](firmware-onto-a-new-board.md)).
- Re-seat the board once.  On macOS, `ls /dev/cu.*` shows the raw port list when `discover` comes up empty.

## `PORT_UNAVAILABLE`, or `OSError: [Errno 16] Resource busy`

Another program is holding the board's USB serial port, which is claimed exclusively.  Mu, Thonny, a `screen` or `minicom` session, a second `run.py` command, or an editor's serial console (VS Code, PyCharm) each hold it, as can an earlier deploy you stopped with Ctrl-C.

Run the doctor to see which program has the port:

```bash
python3 run.py doctor
```

It lists the held ports and the process IDs holding them.  Close that program, tap the board's RESET button, and wait 2-3 seconds for the port to re-enumerate before retrying.

## `[Errno 13] Permission denied: '/dev/ttyACM0'` on Linux

On Linux the serial port is owned by a group (`dialout` on Debian and Ubuntu, `uucp` on Arch), and your user account isn't in it.

```bash
sudo usermod -a -G dialout $USER   # Debian/Ubuntu; use uucp on Arch
```

Log out and back in for the group change to take effect, then replug.

## `RAW_REPL_UNRESPONSIVE`: the board's REPL did not respond

The board's interactive Python prompt (its REPL) isn't answering, usually because the board is wedged, sitting in CircuitPython safe mode (a recovery state it enters after a crash), or running code that ignores Ctrl-C.

Tap RESET.  If the board is in CircuitPython safe mode, press any key over the serial connection to leave it.  If it stays silent, hold RESET for two seconds, or unplug and replug.

## The deploy hangs for 120 seconds, then retries into the same hang (`COMMAND_TIMED_OUT`)

The board's USB serial link has wedged, and a wedged link never clears on its own, so each retry meets the identical timeout.

Physically unplug and replug the board.  A soft reset over serial will not clear this.  If the board is still dead after a replug, wipe its filesystem or reflash its runtime:

```bash
python3 run.py reset-board --device <id> --yes
```

`reset-board` erases every user file on the board, so back up anything that lives only there first (see the warning on [Getting firmware onto a new board](firmware-onto-a-new-board.md)).  If a wipe doesn't help, reflash the firmware.

## `runtime mismatch: probe says micropython, entry says circuitpython`

The `--runtime` you passed to `add-device` disagrees with what the board reports about itself when the tool probes it.

Re-run `add-device` with the runtime the probe found, or omit `--runtime` to let it auto-detect:

```bash
python3 run.py add-device <id> --address <port> --runtime circuitpython
```

## A deploy lands on the wrong board, or a board seems to move between ports

macOS reassigns the same `/dev/cu.usbmodem<N>` name to different boards on the same root port, so the port name is not a stable identity for one specific board.

You don't need to do anything, and you shouldn't pin a port.  The tooling identifies each board by its hardware UID (a unique id burned into the chip), updates the cached address on its own when a board drifts to a new port, and fails loudly on a UID mismatch rather than deploying to the wrong board.
