# Start here, trial 4

- Page: `docs/start-here.md`
- Run: `.scratch/cold-writer/calibration/writer-4plain`, draft SHA-256
  `0b657afb2a235bfc4545060e2b8734de03eba1ce3bbacf4119b47ad75eebeec4`, written
  with `--voice plain` from brief-4c
- Verdict: accepted
- Owner said: "plain looks good"
- Context: the sibling run `writer-4b` (SHA-256
  `e86c6254512bd24df12da8d382df2f238ffc5f156bd9faed20f0ad11b3dc7e0d`, written
  with the `chumicro-docs` register excerpt) tied with this draft in a blind
  comparison and was not chosen; the owner gave no critique of it. Acceptance
  covers the register. The reviewers' brief-level gaps (no step connects the
  board, an unevaluable firmware skip, no backup method, `settings.toml` named
  without a role, five closing links) were open when the verdict was given.

## Draft

---
title: "Start here: run your first ChuMicro project"
---

# Start here

By the end of this page, a Raspberry Pi Pico W will print a greeting in your laptop terminal. You'll then change that greeting and see the new one after a second deploy.

## What you need

- A Raspberry Pi Pico W and a USB cable that carries data, not just power.
- A laptop running macOS or Linux. The board tooling doesn't support native Windows.
- Git, and Python 3.11 or later available as `python3`.
- An internet connection and a text editor.

## Set up the workbench

You do all your ChuMicro work in a *workbench*. The workbench is a folder on your laptop, called `my-workspace` here, that holds your projects and the tools that send them to boards. You create it by cloning a template.

Open a terminal in the folder where the workbench should live. That folder must not already contain a `my-workspace` folder. Then run:

```bash
git clone --depth 1 https://github.com/ChuMicro/ChuMicro-Workbench-Template my-workspace
cd my-workspace
python3 run.py setup
```

`setup` installs the workbench's dependencies into a virtual environment. Every later `run.py` command selects that environment automatically. From here on, run every shell command on your laptop, from inside `my-workspace`.

## Choose your route

This page covers one path: a Pico W running MicroPython 1.27 or later.

- **Other boards or CircuitPython:** use the [firmware guide](troubleshooting/firmware-onto-a-new-board.md) instead of the next section.
- **CircuitPython on macOS:** also read [CIRCUITPY deploy troubleshooting on macOS](troubleshooting/macos-circuitpy.md).

## Install MicroPython firmware

*Firmware* here means MicroPython, the Python runtime that runs on the board itself. If your Pico W already runs the required version or newer, skip to the next section.

> **Warning:** Installing firmware can erase files stored on the board. If the board holds anything you care about, back it up before you start.

1. Download a UF2 release at or above the required version from the [MicroPython Pico W download page](https://micropython.org/download/RPI_PICO_W/).
2. Unplug the board's USB cable.
3. Hold the BOOTSEL button and plug the cable back in. Let go when a drive named `RPI-RP2` appears on your laptop.
4. Copy the UF2 file onto the `RPI-RP2` drive.

The board restarts and the drive disappears. Leave the USB cable connected.

## Register the board

The board's USB connection appears on your laptop as a *serial port*. Only one program can hold a serial port at a time. *Registration* saves the board's identity under a name that later commands use. Before you register, close any program that might be holding the port, such as Thonny or an editor's serial monitor. Then run:

```bash
python3 run.py bootstrap first-board
```

The command probes the USB serial ports and saves the board as `first-board`. If your laptop has only one serial port, the command picks it for you. If it has several, you'll see a numbered list of every serial port on the laptop, including built-in macOS ones. Choose the Pico W: `/dev/cu.usbmodem<N>` on macOS, or `/dev/ttyACM<N>` on Linux.

Registration worked if you see this line and no warning follows it:

```text
add-device: registered first-board (micropython)
```

If a warning follows the line, it starts with a header like this:

```text
add-device: warning: micropython firmware compatibility:
```

- **The header names MicroPython:** the firmware is too old. Do the firmware install above. Then, with the same Pico W connected, refresh the saved entry:

  ```bash
  python3 run.py bootstrap first-board --force
  ```

  The success line appears again with no warning after it.
- **The header names another implementation:** see the [firmware guide](troubleshooting/firmware-onto-a-new-board.md).
- **The command can't connect to the board:** see [Board not found](troubleshooting/board-not-found.md).

## Create a project

```bash
python3 run.py new hello_board
```

This creates `projects/hello_board/` with a starter program that prints a greeting.

## Deploy and see the greeting

*Deployment* copies a project from your laptop to a named board and then starts it. As with registration, no other program can be holding the board's serial port.

> **Warning:** A default deploy deletes board files that aren't part of the project. That includes a `settings.toml` that exists only on the board. The deploy keeps only a small reserved set of files, and `settings.toml` is never among them. Before your first deploy, back up any board files you want to keep. See the [deployment file rules](troubleshooting/deploys-and-file-persistence.md).

```bash
python3 run.py deploy hello_board --device first-board --tail 30
```

`--tail 30` watches the board's serial output for 30 seconds after the deploy and then returns your prompt. Look for this greeting:

```text
hello from a ChuMicro project
```

The greeting can appear among the deploy messages, before the 30-second window starts, so read the whole output. If it isn't there, see [troubleshooting](troubleshooting/README.md).

## Change the greeting

The project's entry point is the `run()` function in `projects/hello_board/app.py`. ChuMicro calls `run()` when the project starts, so the board behaves differently after your next deploy if you change it.

1. Open `projects/hello_board/app.py` on your laptop.
2. Replace the file's whole contents with:

   ```python
   def run():
       print("Hello from my workbench!")
   ```

3. Save the file.
4. Run the same deploy command again.

This time the output includes:

```text
Hello from my workbench!
```

## Next steps

Optional tasks:

- [Install libraries](install.md)
- [Set up WiFi credentials](wiring-wifi-credentials.md)

Further reading:

- [Questions people ask](faq.md)
- [ChuMicro library reference](https://chumicro.com/ChuMicro/)
- [Workbench template examples](https://github.com/ChuMicro/ChuMicro-Workbench-Template/tree/main/examples)
