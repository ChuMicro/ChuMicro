---
title: "ChuMicro guides: getting started, installing, and fixing CircuitPython and MicroPython boards"
---

# Guides

ChuMicro is a set of Python libraries for CircuitPython and MicroPython boards (timers, buttons, WiFi, MQTT, HTTP, storage), built to run together inside your `while True:` loop, plus laptop tools that put your code on a board.  These guides take you from a new board to a working project, and help when something goes wrong.

New to all of this?  Read the first two pages in order.

- **[Start here](start-here.md)** goes from a board still in its packaging to your own blink running on it, then onto your WiFi: installing a runtime, registering the board, writing a project, and deploying it.
- **[Coming from Arduino](coming-from-arduino.md)** maps the habits you already have, Arduino's `setup()` and `loop()` or the `while True:` and `time.sleep()` of Adafruit Learn guides, onto ChuMicro code.
- **[Installing libraries](install.md)** adds one library to a board you already use: circup on CircuitPython, mip on MicroPython, pip on your laptop, plus the pre-compiled `.mpy` packages and the stable and experimental channels.
- **[Questions people ask](faq.md)** covers why a board freezes on the network, whether any of this uses async, how the same code runs on CircuitPython and MicroPython, and what a library costs in flash.
- **[Troubleshooting](troubleshooting/README.md)** starts from the error text, the hang, or the missing drive: a board that will not show up, WiFi that will not connect, TLS that fails, a deploy that is refused, memory that runs out.
- **[Wiring WiFi credentials](wiring-wifi-credentials.md)** shows how a network name and password reach a board without living in your code or your git history.

Each library has its own guide and API reference, linked from [the documentation home](https://chumicro.com/ChuMicro/).  The contributing pages further down the menu are for changing ChuMicro itself.
