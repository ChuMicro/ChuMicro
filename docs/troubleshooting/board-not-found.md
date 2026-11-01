# Board not found

A plugged-in board is missing from `python3 run.py discover`, or a deploy or REPL session fails to reach it. A data cable, a changed port name, or another program holding the port causes most of these. A Mac's `CIRCUITPY` drive problems are on [CIRCUITPY on macOS](macos-circuitpy.md).

## Nothing shows up in `discover`

Run `python3 run.py discover` with the board unplugged, then again with it plugged in. A new line in the second list is the board's serial port.

When no new line appears:

- Swap the USB cable for one you know carries data. Many cheap cables carry only power, so the board lights up and the laptop never sees it.
- Plug the board straight into the laptop, without a hub.
- Look for a new drive named `RPI-RP2`, or a name ending in `BOOT`. That drive is the board's bootloader, waiting for a Python runtime. [Getting firmware onto a new board](firmware-onto-a-new-board.md) takes it from there.
- On Linux, a port that appears and refuses to open is a permissions problem. [`Permission denied` on Linux](#errno-13-permission-denied-devttyacm0-on-linux) has the fix.

## `PORT_UNAVAILABLE`, or `OSError: [Errno 16] Resource busy`

Ask `doctor` which program holds the port:

```bash
python3 run.py doctor
```

The `SERIAL PORTS` line names each registered board whose port is held, with the process ID and name of the program holding it. Mu, Thonny, a `screen` or `minicom` session, CoolTerm, the serial monitor in VS Code or PyCharm, and an earlier deploy stopped with Ctrl-C are the usual holders.

Close that program, tap the board's RESET button, wait two or three seconds for the port to come back, and retry. A serial port takes one program at a time.

When `doctor` names no holder, check whether the board moved to a new port name, as [a board that worked yesterday](#a-board-that-worked-yesterday-is-unavailable-today-or-a-deploy-reaches-the-wrong-board) describes.

## `[Errno 13] Permission denied: '/dev/ttyACM0'` on Linux

Add your user to the serial-port group, `dialout` on Debian and Ubuntu or `uucp` on Arch:

```bash
sudo usermod -a -G dialout $USER   # Debian/Ubuntu; use uucp on Arch
```

Log out and back in so the new group takes effect, then replug the board. Linux lets only members of that group open serial ports.

## `RAW_REPL_UNRESPONSIVE`: the board's REPL did not respond

Tap RESET and retry.

A CircuitPython board that crashed into safe mode prints `Press reset to exit safe mode.`, and RESET leaves safe mode. A board running code that ignores Ctrl-C needs RESET held for two seconds, or an unplug and replug.

The tools drive a board through its REPL, the `>>>` Python prompt it offers over USB. This error means that prompt stopped answering.

## The deploy hangs, then fails with `COMMAND_TIMED_OUT`

Unplug the board and plug it back in. A software reset leaves the board in the same state.

When the board stays unresponsive after a replug, wipe its files:

```bash
python3 run.py reset-board --device <id> --yes
```

`reset-board` erases every file on the board, `settings.toml` and `boot.py` included, so copy off anything that exists only there first. When the board still stays silent after the wipe, reflash its firmware with [Getting firmware onto a new board](firmware-onto-a-new-board.md).

The board's USB serial link has locked up. It stays locked until the replug, so a retry meets the same timeout.

## A board that worked yesterday is "unavailable" today, or a deploy reaches the wrong board

Compare the port each registered board had with the ports that exist now:

```bash
python3 run.py devices     # the port each registered board had
python3 run.py discover    # the ports that exist right now
```

When the two disagree, refresh the stored port:

```bash
python3 run.py add-device <id> --force
```

`add-device --force` keeps the board's id, picks the only serial port it sees or asks you to choose one, probes the board there, and saves the new port.

A laptop names serial ports as boards arrive: `/dev/cu.usbmodem1101` on a Mac, `/dev/ttyACM0` on Linux. Replugging, switching USB sockets, or adding a second board can give a board a new name, or give its old name to a different board. `devices.yml` keeps the port name recorded at registration.

CircuitPython deploys that copy files through the `CIRCUITPY` drive match the drive to the board by the chip's unique ID. [Two CircuitPython boards](macos-circuitpy.md#two-circuitpython-boards-and-the-deploy-picks-the-wrong-drive) covers that case.

## Deploys fail after the board is reflashed with the other runtime

Check the runtime each entry records:

```bash
python3 run.py devices
```

When an entry names the runtime the board no longer runs, rebuild the entry from the board itself:

```bash
python3 run.py reset-device <id> --yes
```

`reset-device` keeps the id and its place as a default board, probes the board for the runtime it now runs, and rewrites the rest of the entry. It drops a `description` or `deploy_mode` set by hand, so add those back afterwards.

Moving a board from CircuitPython to MicroPython, or back, leaves its `devices.yml` entry naming the old runtime. The tools then talk to the board in the old runtime's protocol.
