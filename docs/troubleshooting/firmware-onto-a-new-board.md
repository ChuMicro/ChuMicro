# Getting firmware onto a new board

ChuMicro code runs on a board that already carries CircuitPython or MicroPython. Each of those is *firmware*: the Python runtime that lives in the board's flash and runs your files. A board fresh from the shop may carry no runtime, an Arduino sketch, or a runtime too old for the libraries.

Flashing firmware replaces whatever the board was running. Copy off any files you want to keep first.

## A drive named `RPI-RP2` appears, or the tool reports `NO_PYTHON_RUNTIME`

The board has no Python runtime. A board waiting in its *bootloader*, the small built-in program that accepts new firmware, shows up on your laptop as a USB drive: `RPI-RP2` on a Raspberry Pi Pico, or a name ending in `BOOT` on many Adafruit boards. A board running an Arduino sketch shows a serial port, and `python3 run.py bootstrap` gets no Python answer from it.

### A board not yet registered

Flash it by hand, the way Adafruit Learn guides do. `install-firmware` reads the board's details from `devices.yml`, so it works only on a registered board.

- **Raspberry Pi Pico, Pico W, Pico 2 W, and other boards that show a drive:** hold the BOOTSEL button while you plug the board in, or double-tap RESET on many Adafruit boards, so the bootloader drive appears. Download the `.uf2` file for your exact board from [circuitpython.org/downloads](https://circuitpython.org/downloads) or [micropython.org/download](https://micropython.org/download/), and drag it onto the drive. The drive disappears and the board restarts running the new runtime.
- **ESP32 boards with no bootloader drive:** follow the instructions on your board's download page. circuitpython.org offers a browser-based installer for many ESP32-S2 and ESP32-S3 boards, and each micropython.org board page gives the `esptool` commands.

Then register the board:

```bash
python3 run.py bootstrap
```

### A registered board that now runs something else

When a board in `devices.yml` has lost its runtime, to an Arduino sketch for example, `install-firmware` downloads the right image and flashes it. It tries to put the board into its bootloader itself, and asks you to press the buttons when it can't.

```bash
# Raspberry Pi Pico family (RP2040, RP2350)
python3 run.py install-firmware --method uf2 --device <id>

# ESP32 family; --erase clears the old firmware and every file first
python3 run.py install-firmware --method esptool --erase --device <id>
```

`install-firmware` picks the image from the board's entry in `devices.yml`. When the entry leaves it unable to choose, it says so: copy the firmware link from the runtime's download page and pass it with `--url <link>`.

## Registering a board warns `Firmware below the supported floor`

Upgrade the firmware before chasing any other error:

```bash
python3 run.py install-firmware --method uf2 --device <id>        # Pico family
python3 run.py install-firmware --method esptool --device <id>    # ESP32 family
```

ChuMicro libraries are tested on MicroPython 1.27 and newer and CircuitPython 10.1 and newer. Boards often ship with older firmware. `add-device` and `bootstrap` register an older board anyway, and print the version it runs next to the version it needs. On older firmware, imports and calls fail in confusing ways at deploy time.

## An ESP32-S2 goes silent while flashing, and esptool reports `No serial data received`

Put the board into its bootloader by hand: hold BOOT (labelled `0` on some boards), press and release RESET, then release BOOT. `install-firmware` waits for exactly this when it prompts you, so press the buttons at the prompt and it carries on.

On MicroPython, an ESP32-S2 such as the Lolin S2 Mini enters its bootloader when the tool asks, then never brings its USB connection back, so the flash can't start. CircuitPython on the same board enters its bootloader without help.
