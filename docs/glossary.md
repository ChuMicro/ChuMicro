---
title: "ChuMicro glossary: ticks, services, runners, deploys, and the other words in these docs"
---

# Glossary

[How it works](how-it-works.md) introduces the main terms in order, from the `while True:` loop to a deploy.  Entries here sort by their first letter, ignoring backticks and a leading dot.

## A

### `app.py`

`app.py` holds a workspace project's program, with setup and the `while True:` loop inside a function named `run()`.  A deploy adds a `code.py` or `main.py` that calls `run()` when the board starts.  See [Single project, boot-shim layout](https://chumicro.com/ChuMicro/workspace/stable/guide/#single-project-boot-shim-layout).

## B

### backoff

Backoff is a pause between retries that doubles after each failed attempt, up to a limit.  See [How do I keep WiFi connected?](faq.md#how-do-i-keep-wifi-connected-on-a-pico-w-or-an-esp32)

### bootloader

A bootloader is the small built-in program that accepts new firmware.  A board waiting in its bootloader shows up on a laptop as a USB drive, such as `RPI-RP2` on a Raspberry Pi Pico.  See [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md#a-drive-named-rpi-rp2-appears-or-the-tool-reports-no_python_runtime).

### BOOTSEL

BOOTSEL is the button on a Raspberry Pi Pico that starts the [bootloader](#bootloader) when it is held down while the board is plugged in.  See [A board not yet registered](troubleshooting/firmware-onto-a-new-board.md#a-board-not-yet-registered).

### bundle

A bundle is a GitHub repository that holds every ChuMicro library in the layout `circup` and `mip` install from.  See [circup and the ChuMicro bundle](install.md#circuitpython-circup-and-the-chumicro-bundle).

## C

### channel

A channel is the release line a library comes from: stable for tagged releases, or experimental for pre-releases built from `main`.  See [Experimental (pre-release) channel](install.md#experimental-pre-release-channel).

### `check()` and `handle()`

`check(now_ms)` returns `True` when a [service](#service) has work to do.  `handle(now_ms)` does one small piece of that work and returns.  See [Services](https://chumicro.com/ChuMicro/runner/stable/guide/#services).

### CIRCUITPY

CIRCUITPY is the USB drive a CircuitPython board shows on a laptop.  It holds `code.py`, a `lib/` folder of libraries, and any other file the program reads.  See Adafruit's [The CIRCUITPY drive](https://learn.adafruit.com/welcome-to-circuitpython/the-circuitpy-drive).

### CircuitPython

CircuitPython is Adafruit's Python for microcontroller boards, built from MicroPython.  See [Put CircuitPython or MicroPython on the board](start-here.md#1-put-circuitpython-or-micropython-on-the-board).

### circup

`circup` is Adafruit's command-line installer for CircuitPython libraries.  It copies a library by name into the `lib/` folder on the [CIRCUITPY](#circuitpy) drive.  See [circup and the ChuMicro bundle](install.md#circuitpython-circup-and-the-chumicro-bundle).

### `code.py` and `main.py`

CircuitPython runs `code.py` when the board starts.  MicroPython runs `main.py`.  See [Single project, boot-shim layout](https://chumicro.com/ChuMicro/workspace/stable/guide/#single-project-boot-shim-layout).

### connector

A connector is a `chumicro_sockets` object that opens a TCP or TLS connection one step at a time: look up the server's address, connect, then finish the TLS handshake.  Its `state` reads `"ready"` or `"failed"` once it is done.  See [the sockets guide](https://chumicro.com/ChuMicro/sockets/stable/guide/#overview).

### CPython

CPython is the standard Python on a laptop or desktop, where the laptop tools run and where the libraries' tests run.  See [CPython: pip](install.md#cpython-pip).

## D

### `Deadline`

`Deadline` is a one-shot timer from `chumicro_timing`.  `Deadline(5000, now_ms)` answers `expired(now_ms)` with `True` once 5 seconds have passed.  See [Giving up after a while](https://chumicro.com/ChuMicro/timing/stable/guide/#giving-up-after-a-while).

### demo

A demo is a small project under `demos/` in the ChuMicro repository that runs a board and your laptop as the two ends of a real exchange, started by one command.  See [What a demo is](https://github.com/ChuMicro/ChuMicro/blob/main/demos/README.md#what-a-demo-is).

### `DEMO_COMPLETE`

`DEMO_COMPLETE` is the [marker line](#marker-line) a demo's board program prints after its first full pass.  The demo's `driver.py` on the laptop watches for it.  See [Adding a demo](https://github.com/ChuMicro/ChuMicro/blob/main/demos/README.md#adding-a-demo).

### deploy

A deploy copies a project from your laptop onto a board, with the libraries it imports and [`/runtime_config.msgpack`](#runtime_configmsgpack), then restarts the board.  It also removes board files the project does not include.  See [Deploys and file persistence](troubleshooting/deploys-and-file-persistence.md).

### `devices.yml`

`devices.yml` is the workspace file that lists your boards, each with the id, serial port, and runtime that `bootstrap` or `add-device` recorded.  See [The three `devices.yml` zones](https://chumicro.com/ChuMicro/workspace/stable/guide/#the-three-devicesyml-zones).

## E

### esptool

`esptool` is Espressif's command-line tool that writes firmware to ESP32 boards over the serial port.  `install-firmware --method esptool` runs it.  See [A registered board that now runs something else](troubleshooting/firmware-onto-a-new-board.md#a-registered-board-that-now-runs-something-else).

### example

An example is one short program in a library's `examples/` folder that shows that library alone.  `chumicro-workspace deploy-example <library> <name>` puts one on a board.  See [Demo or example?](https://github.com/ChuMicro/ChuMicro/blob/main/demos/README.md#demo-or-example)

## F

### fake

A fake is a stand-in a library ships in its `testing` module, such as `FakeTicks`, a clock that moves only when a test says so.  Fakes let board code run under pytest on a laptop.  See [Can I test my project without hardware?](faq.md#can-i-test-my-project-without-hardware)

### firmware

Firmware is the runtime, CircuitPython or MicroPython, installed in a board's [flash](#flash), where it runs your files.  See [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md).

### flash

Flash is a board's built-in storage, where the firmware and your files live.  To flash a board is to write new firmware into it.  See [Getting firmware onto a new board](troubleshooting/firmware-onto-a-new-board.md).

### flash deploy

A flash deploy, the default mode, writes your files to the board's storage, where they survive a reset.  See [Deploys and file persistence](troubleshooting/deploys-and-file-persistence.md#the-deploy-prints-switching-to-flash-mode-after-you-asked-for-ram).

## G

### generator task

A generator task is a [job](#job) written as one function with [`yield from`](#yield-from) lines, registered with `runner.add_generator()`.  Each `yield from` pauses the task and lets the other jobs run.  See [Generator tasks](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks).

## J

### job

A job is anything registered with a [runner](#runner): a [timed job](#timed-job), a [service](#service), or a [generator task](#generator-task).  See [the runner guide](https://chumicro.com/ChuMicro/runner/stable/guide/#overview).

## L

### `load_runtime_config()`

`load_runtime_config()` from `chumicro_config` reads `/runtime_config.msgpack` on the board.  It returns your settings keyed by dotted names, such as `config["wifi.ssid"]`.  See [What the deploy does with it](wiring-wifi-credentials.md#what-the-deploy-does-with-it).

## M

### marker line

A marker line is a line a demo's board program prints as `NAME key=value`, such as `WIFI_OK ip=192.168.1.20`, for the laptop-side driver to read.  The driver skips indented and lowercase lines, which are for people.  See [Adding a demo](https://github.com/ChuMicro/ChuMicro/blob/main/demos/README.md#adding-a-demo).

### MicroPython

MicroPython is a Python for microcontroller boards, from micropython.org.  See [Put CircuitPython or MicroPython on the board](start-here.md#1-put-circuitpython-or-micropython-on-the-board).

### mip and mpremote

`mpremote` is MicroPython's command-line tool for a board on USB.  `mip` is MicroPython's package installer, which `mpremote mip install` runs from your laptop.  See [MicroPython: mip](install.md#micropython-mip).

### `.mpy` file

An `.mpy` file is a Python module compiled ahead of time to bytecode, which loads faster and uses less RAM on a board than its `.py` source.  See [Pre-compiled `.mpy` bytecode](install.md#pre-compiled-mpy-bytecode).

### MQTT

MQTT is a small publish-and-subscribe protocol that home-automation systems use.  A board publishes messages to a *broker*, a server that passes each one on to the devices subscribed to its topic.  See [How do I use MQTT on CircuitPython?](faq.md#how-do-i-use-mqtt-on-circuitpython-without-freezing-everything-else)

## N

### `next_deadline()`

`next_deadline(now_ms)` is an optional [service](#service) method that returns the tick by which the service must run next, such as a WiFi retry or an MQTT keepalive.  `runner.wait()` reads it and wakes in time.  See [How `wait()` decides how long to sleep](https://chumicro.com/ChuMicro/runner/stable/guide/#how-wait-decides-how-long-to-sleep).

### `now_ms`

`now_ms` is the clock reading, in milliseconds, that `runner.tick()` takes once per pass, passes to every job it runs, and returns.  See [the runner guide](https://chumicro.com/ChuMicro/runner/stable/guide/#overview).

## P

### pass

A pass is one trip round the `while True:` loop.  In a runner loop, a pass is one `runner.tick()` and one `runner.wait()`.  See [How it works](how-it-works.md#a-runner-calls-every-job-for-you).

### periodic task

A periodic task is another name for a [timed job](#timed-job).

### project

A project is a folder under `projects/` in a workspace that holds one board program: its [`app.py`](#apppy) and any files that program reads.  See [Workspace layout](https://chumicro.com/ChuMicro/workspace/stable/guide/#workspace-layout).

### `project_config.toml`

`project_config.toml` is a project's own settings file, safe to commit.  A deploy merges it over [`secrets.toml`](#secretstoml), so its value wins for any key both files set.  See [What the deploy does with it](wiring-wifi-credentials.md#what-the-deploy-does-with-it).

## R

### `radio=`

The `radio=` argument passes CircuitPython's WiFi radio to a call that opens a socket, since CircuitPython builds every socket from that radio.  Pass `wifi.adapter.radio` from a `WifiService`, or `wifi.radio` from CircuitPython's own `wifi` module.  See [Platform notes](https://chumicro.com/ChuMicro/sockets/stable/guide/#platform-notes).

### RAM deploy

A RAM deploy runs your code from the board's memory without writing it to storage, so nothing it sends survives a reset.  See [Deploys and file persistence](troubleshooting/deploys-and-file-persistence.md#the-deploy-prints-switching-to-flash-mode-after-you-asked-for-ram).

### `Rate`

`Rate` is a repeating timer from `chumicro_timing`.  `blink = Rate(500, now_ms)` makes `blink.due(now_ms)` answer `True` once every 500 ms.  See [the timing guide](https://chumicro.com/ChuMicro/timing/stable/guide/#overview).

### REPL

The REPL, short for read-eval-print loop, is a board's interactive Python prompt.  `python3 run.py repl` opens it.  See [REPL](https://chumicro.com/ChuMicro/workspace/stable/guide/#repl).

### runner

A runner, a `Runner` from `chumicro_runner`, holds a program's [jobs](#job) and runs each one when it is due.  The loop drives it with two lines: `now_ms = runner.tick()` and `runner.wait(now_ms)`.  See [the runner guide](https://chumicro.com/ChuMicro/runner/stable/guide/#overview).

### `runner.tick()`

`runner.tick()` reads the clock once, asks each due service's `check()`, runs every due job, and returns [`now_ms`](#now_ms).  See [Order within a tick](https://chumicro.com/ChuMicro/runner/stable/guide/#order-within-a-tick).

### `runner.wait()`

`runner.wait(now_ms)` sleeps until the next job is due, a service's [`next_deadline()`](#next_deadline) arrives, or a watched [socket](#socket) has data.  See [How `wait()` decides how long to sleep](https://chumicro.com/ChuMicro/runner/stable/guide/#how-wait-decides-how-long-to-sleep).

### `run.py`

`run.py` is the script at the top of a workspace that runs every laptop command, such as `python3 run.py deploy <project>`.  The ChuMicro repository's own `scripts/run.py` is a separate tool, for contributors.  See [Get the workbench](start-here.md#2-get-the-workbench).

### runtime

A runtime is the Python a board runs, CircuitPython or MicroPython, or the CPython on a laptop.  See [Put CircuitPython or MicroPython on the board](start-here.md#1-put-circuitpython-or-micropython-on-the-board).

### `runtime_config.msgpack`

`/runtime_config.msgpack` is the settings file a deploy writes to the board, built from [`secrets.toml`](#secretstoml) and the project's [`project_config.toml`](#project_configtoml).  See [What the deploy does with it](wiring-wifi-credentials.md#what-the-deploy-does-with-it).

## S

### `secrets.toml`

`secrets.toml` is the file at the top of a workspace that holds your WiFi password and other credentials.  Git ignores it.  See [The smallest secrets.toml](wiring-wifi-credentials.md#the-smallest-secretstoml).

### serial port

A serial port is the USB connection that carries a board's REPL and printed output, such as `/dev/cu.usbmodem1101` on a Mac.  `python3 run.py discover` lists the serial ports a laptop sees.  See [Nothing shows up in `discover`](troubleshooting/board-not-found.md#nothing-shows-up-in-discover).

### service

A service is an object with [`check(now_ms)` and `handle(now_ms)`](#check-and-handle) methods that a runner calls in turn.  `Button`, `WifiService`, and `MQTTClient` are services.  See [Services](https://chumicro.com/ChuMicro/runner/stable/guide/#services).

### `settings.toml`

`settings.toml` is CircuitPython's own settings file on the CIRCUITPY drive.  A workspace deploy removes it from the board.  See [CircuitPython auto-connect](wiring-wifi-credentials.md#circuitpython-auto-connect).

### `Signal` and `wait_for()`

A `Signal` from `chumicro_timing.waits` is a flag one part of a program sets with `signal.set()`.  A [generator task](#generator-task) pauses on `yield from wait_for(signal)` until the flag is set.  See [Waiting for a callback](https://chumicro.com/ChuMicro/runner/stable/guide/#waiting-for-a-callback).

### socket

A socket is one end of a network connection.  A network service names its socket so `runner.wait()` wakes when data arrives on it.  See [Network services](https://chumicro.com/ChuMicro/runner/stable/guide/#network-services).

## T

### tick

A tick is a reading of the board's millisecond counter, as [`ticks_ms()`](#ticks_ms) returns it.  The runner guide also calls one call to [`runner.tick()`](#runnertick) a tick.  See [the timing guide](https://chumicro.com/ChuMicro/timing/stable/guide/#overview).

### `ticks_add()` and `ticks_diff()`

`ticks_diff(end, start)` returns the milliseconds from one tick to another, correct across [wraparound](#wraparound).  `ticks_add(tick, delta)` returns the tick `delta` milliseconds on, correct across it too.  See [Using ticks directly](https://chumicro.com/ChuMicro/timing/stable/guide/#using-ticks-directly).

### `ticks_ms()`

`ticks_ms()` from `chumicro_timing` reads the board's millisecond counter on every runtime, like Arduino's `millis()`.  See [Using ticks directly](https://chumicro.com/ChuMicro/timing/stable/guide/#using-ticks-directly).

### timed job

A timed job is a plain function a runner calls every `period_ms`, registered with `runner.add_periodic(function, period_ms=...)`.  See [Timed jobs](https://chumicro.com/ChuMicro/runner/stable/guide/#timed-jobs).

### TLS

TLS is the encryption behind `https://` and `wss://` addresses.  See [TLS and HTTPS failures](troubleshooting/tls-https-failures.md).

## U

### UF2

UF2 is a firmware file format that a board's [bootloader](#bootloader) drive takes by drag and drop.  The Raspberry Pi Pico family takes its firmware as a `.uf2` file.  See [A board not yet registered](troubleshooting/firmware-onto-a-new-board.md#a-board-not-yet-registered).

### unix port

A unix port is a desktop build of MicroPython or CircuitPython that runs on a laptop.  ChuMicro runs every library's tests on the MicroPython and CircuitPython unix ports, which catches code that works on CPython and fails on a board.  See [Cross-runtime testing](contributing/cheat-sheet.md#cross-runtime-testing).

## V

### virtual environment

A virtual environment is a private copy of Python and its packages inside one folder.  `python3 run.py setup` builds one inside a workspace for the laptop tools.  See [Get the workbench](start-here.md#2-get-the-workbench).

## W

### workbench

The workbench is ChuMicro's set of laptop tools, such as `chumicro-workspace`, `chumicro-deploy`, and `chumicro-repl`.  The tools run on CPython and stay off the board.  See [`workbench/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench).

### workbench template

The workbench template is the GitHub repository `ChuMicro/ChuMicro-Workbench-Template`, cloned to start a [workspace](#workspace).  See [Get the workbench](start-here.md#2-get-the-workbench).

### workspace

A workspace is your folder of board projects, cloned from the [workbench template](#workbench-template).  It holds `projects/`, [`devices.yml`](#devicesyml), [`secrets.toml`](#secretstoml), and the [`run.py`](#runpy) that runs every command.  See [Workspace layout](https://chumicro.com/ChuMicro/workspace/stable/guide/#workspace-layout).

### wraparound

Wraparound, also called rollover, is the tick counter's return to zero after 2²⁹ milliseconds, about 6.2 days.  Subtracting two ticks with `-` goes wrong across it, which is why [`ticks_diff()`](#ticks_add-and-ticks_diff) exists.  See [How the rollover works](https://chumicro.com/ChuMicro/timing/stable/guide/#how-the-rollover-works).

## Y

### `yield from`

`yield from` is the Python statement a [generator task](#generator-task) pauses on.  `yield from sleep_until(until_ms)` hands the loop to the runner until that tick arrives.  See [Generator tasks](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks).
