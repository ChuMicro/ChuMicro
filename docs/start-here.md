---
title: "Start here: run your first ChuMicro project"
---

# Start here

This quickstart takes you from a Raspberry Pi Pico W to a running greeting that you edit on your laptop and send back to the board. You keep projects on the laptop, and ChuMicro copies them to the board and starts them.

## What you need

- A Raspberry Pi Pico W
- A USB data cable
- A laptop with Git and Python 3.11 or later available as `python3`
- An internet connection
- A text editor

## Choose your route

This page uses MicroPython 1.27 or later for its Pico W instructions. If you use another board or CircuitPython, install firmware with [Put firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md) instead of following the firmware steps below. On macOS, CircuitPython users can also read [Connect a CIRCUITPY board on macOS](troubleshooting/macos-circuitpy.md).

<a id="1-get-the-workbench"></a>

## Get the workbench

ChuMicro's workbench template gives you a workspace for laptop projects and the tools that send them to boards. Open a terminal in a parent folder where `my-workspace` will be a new directory, then clone and set it up:

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
python3 run.py setup
```

The `setup` command installs dependencies into a virtual environment. Later `run.py` commands select that environment automatically. Run every remaining shell command on the laptop, from `my-workspace`.

<a id="2-put-a-runtime-on-the-board"></a>

## Put MicroPython on the Pico W

MicroPython is firmware that runs Python on the Pico W. If you know your board already runs MicroPython 1.27 or later, skip to registration.

> **Warning:** Installing firmware can erase files on the board. Back up any valuable files first.

1. Download a Pico W release in UF2 format, version 1.27 or later, from <https://micropython.org/download/RPI_PICO_W/>.
2. Disconnect the board from USB.
3. Hold the BOOTSEL button while you reconnect the board, and release it when a drive named `RPI-RP2` appears.
4. Copy the UF2 file to the `RPI-RP2` drive.

The board restarts and the drive disappears. Leave the USB cable connected.

<a id="3-register-the-board"></a>

## Register the board

Registration saves the board's identity under a name that later commands use. First, close any program using the board's serial connection, such as Thonny or an editor's serial monitor, and keep it closed during deployment. Temporarily disconnecting other serial devices also makes this board easier to choose.

```bash
python3 run.py bootstrap first-board
```

The `bootstrap` command probes the board's USB serial connection. It selects a sole port automatically or offers a numbered choice. It reports through the underlying `add-device` command, and success includes this line with no firmware compatibility warning:

```text
add-device: registered first-board (micropython)
```

If a compatibility warning names MicroPython, install the Pico W firmware described above. Then, with the same Pico W connected, refresh its saved entry:

```bash
python3 run.py bootstrap first-board --force
```

If the warning names another Python implementation, see [Put firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md). If the tool cannot connect, see [Board not found](troubleshooting/board-not-found.md).

<a id="4-make-a-project-and-send-it-over"></a>

## Create a project

Create a starter project on the laptop:

```bash
python3 run.py new hello_board
```

This creates `projects/hello_board/`, whose starter program prints a greeting.

## Deploy the project

Deploying copies a laptop project to the named board and starts it.

> **Warning:** By default, deployment deletes board files outside the project, except a small reserved set. This includes settings stored only on the board, such as `settings.toml`. Before your first deploy, back up any existing files you want to keep, and read [Deploys and file persistence](troubleshooting/deploys-and-file-persistence.md).

```bash
python3 run.py deploy hello_board --device first-board --tail 30
```

The `--tail 30` option watches serial output for 30 seconds after deployment, then returns you to the laptop prompt. Look for the greeting, which can appear earlier among the deploy messages:

```text
hello from a ChuMicro project
```

If the greeting is absent, inspect the whole command output and follow [Troubleshooting](troubleshooting/README.md).

## Edit and redeploy

The file `projects/hello_board/app.py` defines a `run()` function, and ChuMicro calls `run()` when the project starts. Changing that function changes what the board does once the new file reaches the board.

Open `projects/hello_board/app.py` on the laptop, replace its entire contents with the following, and save:

```python
def run():
    print("Hello from my workbench!")
```

Deploy again to send the change:

```bash
python3 run.py deploy hello_board --device first-board --tail 30
```

The output now includes the new greeting:

```text
Hello from my workbench!
```

<a id="where-to-go-next"></a>

## Next steps

Optional tasks:

- <a id="5-add-a-library"></a>[Install libraries](install.md)
- <a id="6-give-it-your-wifi-password"></a>[Add WiFi credentials](wiring-wifi-credentials.md)

Further reading:

- [FAQ](faq.md)
- [ChuMicro documentation](https://chumicro.com/ChuMicro/)
- [Workbench template examples](https://github.com/ChuMicro/ChuMicro-Workbench-Template/tree/main/examples)
