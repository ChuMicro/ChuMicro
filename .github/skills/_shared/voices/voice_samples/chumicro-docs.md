# chumicro-docs: real-text samples

- Person: none; this is the project's own documentation voice, written by the ChuMicro maintainer
- Register: explanatory prose for a capable reader who is new to the project, from the root README's opening and its first code walkthrough
- Source: `README.md` at the repository root, paragraphs copied whole at the revision that added this file; no trims
- Rights: MIT, this repository

## Excerpt 1

ChuMicro is a family of small Python libraries for microcontrollers: WiFi, MQTT, HTTP client and server, WebSockets, sockets, network time, timers, configuration, and storage that survives a reboot.  Each library installs by itself, so a project that only needs a timer gets a timer and nothing else.

The first rule: never stop the program.  A microcontroller usually has several jobs running at once.  It keeps the WiFi alive, stays connected to an MQTT broker (the message hub most home-automation setups talk through), blinks a status LED, watches a button.  Most Python libraries for boards block: while a request waits on a slow server, or WiFi retries a dead router, the entire device freezes and every other job stops with it.  Code that stops the world to wait on a network is a bad foundation for a device, and if you've ever watched a board hang for thirty seconds because the router was unplugged, you already know it.  ChuMicro libraries do their work in small steps inside your loop.  Each pass, every library does a little and hands control back, so a dead network costs you nothing but the network: the LED keeps blinking, the button keeps answering, and you choose how long to wait and what happens when the waiting is over.

The second rule: the same code runs everywhere.  A library written for CircuitPython won't run on MicroPython, and one written for MicroPython won't run on CircuitPython, so changing boards often means porting your project.  Every ChuMicro library runs unmodified on CircuitPython, MicroPython, and the standard Python on your computer.  You can develop and test a program at your desk, then deploy the same files to a Pico W running CircuitPython or an ESP32 running MicroPython.

## Excerpt 2

The first thing every tutorial teaches is `time.sleep()`.  It's also the reason most board code can only do one thing at a time.  Here's the embedded hello world with no sleep in it:

The loop never pauses.  `Rate` answers "is it time yet?", the LED toggles when it is, and the loop moves on either way.  Everything in ChuMicro is built on this shape: the MQTT client, the HTTP server, and the WiFi supervisor each do one small piece of work per pass through the loop, exactly like this blink.  (CircuitPython shown; the MicroPython version differs only in the LED lines, and both ship in [timing's examples](libraries/timing/examples/).)
