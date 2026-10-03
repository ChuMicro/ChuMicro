---
title: "Start here: run your first ChuMicro project"
---

# Start here

Run a program on your Pico W that repeats a greeting and shows a loop counter. Then change one line to count 2, 4, 6. You do not need Python knowledge. This route installs MicroPython 1.27 or later.

<span id="what-you-need"></span>

## Before you start

You need a Raspberry Pi Pico W (not Pico 2 W), a micro-USB data cable, a macOS or Linux laptop, Git, internet access, and a plain-text editor. Windows board tooling is unsupported. See [Troubleshooting](troubleshooting/README.md).

Enter command blocks in your laptop terminal, one line at a time. Press Enter after each line and wait for the prompt before the next.

Your laptop needs Python 3.11 or later, invoked as `python3`. Check:

```bash
python3 --version
```

If it is older, use [python.org](https://www.python.org/downloads/) on macOS or distribution packages on Linux (Debian 12+ and Ubuntu 24.04+ qualify). Repeat the check with the newer interpreter.

On Debian or Ubuntu, install this before setup regardless of the version-check result:

```bash
sudo apt install python3-venv
```

<span id="1-get-the-workbench"></span>

<span id="get-the-workbench"></span>

## Create your workbench

Choose a laptop parent folder for `my-workbench`. This workbench will hold your projects and tools for sending code to boards.

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workbench
cd my-workbench
python3 run.py setup
```

`setup` creates `.venv`, a separate Python environment for the tools. Later commands select it automatically, so manual activation is unnecessary. Fresh, uninterrupted setup includes:

```text
setup: materialized 3 workspace template(s)
  devices.yml
  workspace.yml
  secrets.toml
```

Pip lines beginning `WARNING:` or `[notice]` are informational.

Run all later commands from the `my-workbench` root, beside `run.py`.

Other ChuMicro pages use `chumicro-workspace <cmd>`. Here, use `python3 run.py <cmd>`.

If setup shows pip `ERROR:` or was interrupted, retry:

```bash
rm -rf .venv
python3 run.py setup
```

This keeps existing `devices.yml`, `workspace.yml`, and `secrets.toml`. Continue when setup finishes without an error and all three files are present.

## Connect the board

MicroPython and CircuitPython are firmware, the board’s Python runtime. Connect the board with your data cable and look in the laptop file browser.

A blank Pico W shows `RPI-RP2`. MicroPython shows no drive, instead communicating through a serial port, the laptop endpoint for USB communication. CircuitPython shows `CIRCUITPY`, where board files are accessible. A charge-only cable shows no drive regardless of firmware.

Close Thonny, any editor serial monitor, and `screen` before later board commands. Keep them closed so they do not occupy the serial port.

### Linux access

On Linux, grant access once. On Arch, substitute `uucp` for `dialout`:

```bash
sudo usermod -a -G dialout $USER
```

Log out and log back in, then run `groups`. Expect `dialout`, or `uucp` on Arch. If missing, restart the laptop and run `groups` again. Open a new terminal at `my-workbench`, then unplug and reconnect the board.

<span id="copy-off-files-you-want-to-keep"></span>

## Preserve board files

**Warning:** Firmware installation and the first deploy can erase board files.

If the board is blank or has nothing to keep, continue to [Install MicroPython](#install-micropython).

Otherwise, choose an existing laptop directory, such as `Documents/ChuMicro-board-backup` in your home folder. Create it in the file browser if absent. Keep this separate Documents folder outside `my-workbench` and other code checkouts, outside Git tracking, especially for credential-bearing files. Workbench backups risk filename collisions that overwrite project files.

For CircuitPython, copy wanted files from `CIRCUITPY` into that directory using the file browser.

For MicroPython, use mpremote, its command-line tool, to list board files:

```bash
.venv/bin/mpremote fs ls
```

Before the next command, replace `<folder>` with your chosen path, for example `"$HOME/Documents/ChuMicro-board-backup"`. Keep the quotes. `$HOME` means your home folder.

```bash
.venv/bin/mpremote fs cp :main.py <folder>/main.py
```

The `:` prefix marks a device path. Repeat for each wanted file, using `main.py` as the example. For folders, put `-r` before the paths. Confirm each wanted file appears in the selected laptop folder.

If `mpremote: no device found` appears, close any port holder, follow [Linux access](#linux-access) if applicable, try a different data cable, then retry the failed command.

<span id="2-put-a-runtime-on-the-board"></span>

<span id="put-micropython-on-the-pico-w"></span>

<span id="install-firmware"></span>

## Install MicroPython

If `RPI-RP2` is already visible, do steps 1 and 5.

1. Open [MicroPython Pico W download](https://micropython.org/download/RPI_PICO_W/). Download the newest listed release, MicroPython 1.27 or later, as a `.uf2` firmware file.
2. Unplug the board.
3. Hold BOOTSEL, the Pico W button, while reconnecting the cable.
4. When `RPI-RP2` appears in the file browser, release BOOTSEL.
5. Copy the `.uf2` to `RPI-RP2`. The board restarts automatically and the drive disappears. A macOS improper-ejection alert is expected. Leave the cable connected.

If the drive is missing, repeat from step 2. Still missing, try a different data cable and repeat from step 2. For further failure, see [Troubleshooting](troubleshooting/README.md).

<span id="choose-your-route"></span>

### Optional alternatives

For CircuitPython on Pico W, open [CircuitPython downloads](https://circuitpython.org/downloads), select the exact Raspberry Pi Pico W page, and follow its board-specific installation instructions for the newest stable compatible release, 10.1 or later. Continue to [Register the board](#register-the-board).

For another board, first check [ChuMicro hardware and runtime-build requirements](install.md#board-support). Unsupported boards are outside this route. Only for an eligible board, choose its matching image and installation instructions from [CircuitPython downloads](https://circuitpython.org/downloads) or [MicroPython downloads](https://micropython.org/download/). Use CircuitPython 10.1 or later or MicroPython 1.27 or later, then continue to [Register the board](#register-the-board).

<span id="3-register-the-board"></span>

## Register the board

Registration saves the board’s identity under a reusable name. Use `first-board`:

```bash
python3 run.py bootstrap first-board
```

If prompted with `pick a board:`, type the connected board entry’s number and press Enter. Pico W ports resemble `/dev/cu.usbmodem<N>` on macOS or `/dev/ttyACM<N>` on Linux. Other boards may differ.

If no entry matches, press Enter alone. `add-device: invalid choice ''` means nothing was saved. Follow [Board not found](troubleshooting/board-not-found.md), then retry.

Success looks like this, without a firmware warning:

```text
add-device: registered first-board (micropython)
```

CircuitPython reports `(circuitpython)` instead. This page’s next sections supply the commands for the `bootstrap: ready.  Next steps:` footer.

For Linux `[Errno 13] Permission denied`, follow [Linux access](#linux-access), then retry registration. For missing ports or other detection failures, follow [Board not found](troubleshooting/board-not-found.md), then retry.

### Firmware warnings

```text
add-device: warning: micropython firmware compatibility:
```

This warning means MicroPython is below 1.27 or its version is unreadable. Follow [Install MicroPython](#install-micropython) rather than the printed `install-firmware` advice. Check that the `.uf2` filename indicates v1.27 or later.

For a CircuitPython compatibility warning, use [CircuitPython downloads](https://circuitpython.org/downloads), select the matching board, and follow its installation instructions for the newest stable release, 10.1 or later.

After updating the same board and runtime, refresh its saved entry:

```bash
python3 run.py bootstrap first-board --force
```

Expect the registration success line without a warning.

<span id="4-make-a-project-and-send-it-over"></span>

## Create a project

```bash
python3 run.py new hello_board
```

This creates `projects/hello_board/` with an `app.py` starter file. You will replace it next.

A library is reusable Python code. The `chumicro_runner` library schedules actions. Download it into the laptop’s `libraries/` folder:

```bash
python3 run.py library add chumicro_runner
```

At `pull chumicro_timing? [Y/n]`, press Enter for yes. Runner uses this timing dependency. Successful acquisition includes these lines, with varying versions:

```text
Added chumicro_runner v<version> (stable)
  + chumicro_timing v<version>
```

If acquisition fails or the dependency is missing, follow [Installing ChuMicro libraries](install.md#project-workspaces), using the workbench route. Resolve this before deployment.

## Write your program

Open laptop file `my-workbench/projects/hello_board/app.py` in your plain-text editor. Replace its entire contents with this program, preserve its spaces and colons, and save.

```python
from chumicro_runner import Runner


def say_hello(now_ms):
    print("Hello from my workbench!")


def run():
    runner = Runner()
    runner.add_periodic(say_hello, period_ms=1000)
    count = 0

    while True:
        now_ms = runner.tick()
        count = count + 1
        print("Loop count:", count)
        runner.wait(now_ms)
```

`from chumicro_runner import Runner` makes the library component available. `runner = Runner()` creates the object that gives registered actions their turns. Uppercase `Runner` is the imported name. Lowercase `runner` names that object in this program.

`def` defines a named group of instructions, a function. `say_hello` prints the greeting. `run()` is the function ChuMicro calls at project start. Indentation shows which instructions belong to a function or loop. Keep the copied spaces, with the loop body eight spaces from the left margin.

`runner.add_periodic` registers the greeting action. `period_ms=1000` requests it about once per second. The action receives `now_ms` but does not use it. This scheduled greeting runs beside your loop work and supplies the next wake time for the idle wait.

`count = 0` initializes a remembered number at program start. `while True` repeats its indented body until the program is stopped or replaced, or the board loses power.

Your `app.py` owns the loop and counter instructions. `runner.tick()` gives due registered work, including the greeting, a turn. Its returned `now_ms` is a scheduling tick value, not calendar or wall-clock time. `count = count + 1` increases the number. `print` sends its label and current value to laptop output. `runner.wait(now_ms)` idles until the next registered work is due, then the next loop iteration follows.

<span id="deploy-the-project"></span>

## Deploy and change the loop

Deployment copies your laptop project to the board and starts it. By default, board files outside the payload are removed, except `boot.py`, `boot_out.txt`, and `_chu_kv.msgpack`. You should have completed [Preserve board files](#preserve-board-files).

```bash
python3 run.py deploy hello_board --device first-board --tail 30
```

`--tail 30` watches serial output for 30 seconds, then returns the laptop prompt. The board program keeps running afterward.

Look for recurring greetings and increasing counts, possibly among deployment messages:

```text
Loop count: 1
Hello from my workbench!
Loop count: 2
Hello from my workbench!
Loop count: 3
```

The number of lines during the watch can vary. If this output is missing, see [Troubleshooting](troubleshooting/README.md). `--- traceback ---` means program failure. `deploy: micropython@` or `deploy: circuitpython@` means deployment failure.

<span id="edit-and-redeploy"></span>

In the same `app.py`, inside `while True`, replace `count = count + 1` with `count = count + 2`. Preserve indentation, `tick()` and `wait()`, then save.

After the previous command returns to the laptop prompt, deploy again:

```bash
python3 run.py deploy hello_board --device first-board --tail 30
```

The counter restarts at 2 and advances by 2 while the greeting continues:

```text
Loop count: 2
Hello from my workbench!
Loop count: 4
Hello from my workbench!
Loop count: 6
```

Redeploying turns your saved laptop edit into board behavior.

<span id="where-to-go-next"></span>

<span id="next-steps"></span>

<span id="5-add-a-library"></span>

<span id="6-give-it-your-wifi-password"></span>

## Adding libraries and WiFi

[Installing ChuMicro libraries](install.md#project-workspaces) covers acquiring, inspecting, importing, and deploying reusable code. [WiFi credentials](wiring-wifi-credentials.md) explains putting the network name and password on the board while keeping credentials outside code and Git.
