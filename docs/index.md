---
title: "ChuMicro guides: getting started, installing, and fixing CircuitPython and MicroPython boards"
---

# Guides

ChuMicro is a set of Python libraries for CircuitPython and MicroPython boards, plus laptop tools that put your code on a board.  The libraries cover timers, buttons, WiFi, MQTT, HTTP, and storage.  They all run together inside one `while True:` loop.

## First steps, in order

1. **[Start here](start-here.md)** takes a board from its packaging to your own blink running on it, then puts the board on your WiFi.  Its steps install a runtime, register the board, create a project, and deploy it.
2. **[Coming from Arduino](coming-from-arduino.md)** maps Arduino's `setup()` and `loop()`, and the `while True:` and `time.sleep()` of Adafruit Learn guides, onto ChuMicro code.
3. **[Build a WiFi temperature sensor](tutorial-wifi-sensor.md)** grows a blink, one step at a time, into a board that publishes its temperature over MQTT.

## Reference

- **[How it works](how-it-works.md)** builds from a plain `while True:` loop up to a runner and a deploy, with programs that run on your laptop.
- **[Glossary](glossary.md)** defines the words these guides use, from `app.py` to `yield from`.
- **[Installing libraries](install.md)** gives the install command for each runtime: circup on CircuitPython, mip on MicroPython, and pip on your laptop.  It also covers pre-compiled `.mpy` packages and the experimental channel.
- **[Questions people ask](faq.md)** covers why a board freezes on the network, whether any of this uses async, how the same code runs on CircuitPython and MicroPython, and what a library costs in flash.
- **[Troubleshooting](troubleshooting/README.md)** starts from the error text, the hang, or the missing drive: a board that will not show up, WiFi that will not connect, TLS that fails, a deploy that is refused, memory that runs out.
- **[Wiring WiFi credentials](wiring-wifi-credentials.md)** shows how a network name and password reach a board while staying out of your code and your git history.

Each library has its own guide and API reference, linked from [chumicro.com/ChuMicro](https://chumicro.com/ChuMicro/).  The contributing pages further down the menu are for changing ChuMicro itself.
