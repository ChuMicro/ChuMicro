# Board not found

Your board is plugged in, but `python3 run.py discover` lists nothing for it, or a deploy or REPL session can't reach it. The cause is nearly always the cable, the port name, or another program holding the board. Problems with the CIRCUITPY drive on a Mac have their own page: [CIRCUITPY on macOS](macos-circuitpy.md).

## Nothing shows up in `discover`

Run `python3 run.py discover` with the board unplugged, then again with it plugged in. A new line in the second list is your board's serial port.

If no new line appears:

- Swap the USB cable for one you know carries data. Many cheap cables carry only power: the board lights up but your laptop never sees it.
- Plug straight into the laptop rather than through a hub.
- Look for a new drive named `RPI-RP2`, or a name ending in `BOOT`. That drive means the board is sitting in its bootloader with no Python runtime yet. [Getting firmware onto a new board](firmware-onto-a-new-board.md) takes it from there.
- On Linux, a port that appears but refuses to open is a permissions problem; see the section on `Permission denied` below.

## `PORT_UNAVAILABLE`, or `OSError: [Errno 16] Resource busy`

Only one program at a time can hold a board's serial port, and something else has it.

```bash
python3 run.py doctor
```

The `SERIAL PORTS` line names each registered board whose port is held, with the process ID and name of the program holding it. The usual holders are Mu, Thonny, a `screen` or `minicom` session, CoolTerm, the serial monitor in VS Code or PyCharm, or an earlier deploy you stopped with Ctrl-C. Close that program, tap the board's RESET button, wait two or three seconds for the port to come back, and retry.

If `doctor` reports no holder, the board has probably moved to a different port name; see the section on boards that worked yesterday.

## `[Errno 13] Permission denied: '/dev/ttyACM0'` on Linux

Linux lets only members of one group open serial ports: `dialout` on Debian and Ubuntu, `uucp` on Arch. Add yourself to it:

```bash
sudo usermod -a -G dialout $USER   # Debian/Ubuntu; use uucp on Arch
```

Log out and back in so the new group takes effect, then replug the board.

## `RAW_REPL_UNRESPONSIVE`: the board's REPL did not respond

The tools drive a board through its REPL, the `>>>` Python prompt it offers over USB. That prompt is not answering.

Tap RESET and retry. A CircuitPython board that crashed into safe mode prints `Press reset to exit safe mode.`, and RESET is the way out. If the board runs code that ignores Ctrl-C, hold RESET for two seconds, or unplug it and plug it back in.

## The deploy hangs, then fails with `COMMAND_TIMED_OUT`

The board's USB serial link has locked up. It never recovers on its own, so retrying meets the same timeout.

Unplug the board and plug it back in; a software reset can't clear this. If the board is still unresponsive after a replug, wipe its files:

```bash
python3 run.py reset-board --device <id> --yes
```

`reset-board` erases every file on the board, including `settings.toml` and `boot.py`, so copy off anything that exists only there first. If the board still won't answer after the wipe, reflash its firmware ([Getting firmware onto a new board](firmware-onto-a-new-board.md)).

## A board that worked yesterday is "unavailable" today, or a deploy reaches the wrong board

Your laptop names serial ports as boards arrive (`/dev/cu.usbmodem1101` on a Mac, `/dev/ttyACM0` on Linux), so replugging, switching USB sockets, or adding a second board can hand a board a new name, or hand its old name to a different board. `devices.yml` still holds the name the board had when you registered it.

Compare the two lists:

```bash
python3 run.py devices     # the port each registered board had
python3 run.py discover    # the ports that exist right now
```

When they disagree, refresh the stored port. `add-device` with `--force` keeps the board's id, asks which port to use, checks the board on it, and saves the new port:

```bash
python3 run.py add-device <id> --force
```

CircuitPython deploys that copy files through the CIRCUITPY drive already match the drive to the board by the chip's unique ID; [CIRCUITPY on macOS](macos-circuitpy.md#two-circuitpython-boards-and-the-deploy-picks-the-wrong-drive) covers that case.

## Deploys stopped working after you reflashed the board with the other runtime

Moving a board from CircuitPython to MicroPython, or back, leaves its entry in `devices.yml` naming the old runtime, so the tools talk to it the wrong way. `python3 run.py devices` shows the runtime each entry records.

Rebuild the entry from the board itself:

```bash
python3 run.py reset-device <id> --yes
```

`reset-device` keeps the id and its place as a default board, probes the board to find out which runtime it now runs, and rewrites the rest of the entry. A `description` or `deploy_mode` you set by hand is dropped, so add those back afterwards.
