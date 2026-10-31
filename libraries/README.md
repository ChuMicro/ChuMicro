# ChuMicro libraries

<img src="../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Small Python libraries for CircuitPython and MicroPython boards, each one installed by itself.  Every one of them also runs on your laptop's Python, so you can test board code at your desk.  The libraries that wait on something (WiFi, a server, a button press) do it a small step at a time inside your `while True:` loop, and [`runner`](runner/) gives all of them their turns from that one loop.  The rest, like `msgpack` and `compat`, are plain code you import and call.

<br clear="left">

New here?  Start with [`timing`](timing/) for a loop that never sleeps, add [`buttons`](buttons/) or [`knobs`](knobs/) for input, and bring in [`runner`](runner/) once the loop has more than a couple of jobs or talks to a network.  The [project README](../README.md) walks that path one step at a time, and [Coming from Arduino](../docs/coming-from-arduino.md) maps `setup()`, `loop()`, and `time.sleep()` habits onto it.  The laptop tools that put these libraries on a board live in [`workbench/`](../workbench/).

## Pick a library

| Library | Use it when you need | What you get |
|---|---|---|
| **[timing](timing/)** | Something to happen every N milliseconds, or a time limit, without `time.sleep()` | `Rate` ("is it time yet?"), `Deadline` ("has the time run out?"), and tick math that survives the counter wrapping round. |
| **[runner](runner/)** | Several jobs in one loop, or any of the network libraries | A `Runner` that gives every service and timer its turn on `tick()` and rests the CPU on `wait()`.  Jobs that run in sequence can be written as generators. |
| **[buttons](buttons/)** | A button, switch, or key matrix that never misses a press | Debounced presses, long presses, auto-repeat, and click counts, captured underneath your loop so a tap lands even while the loop is busy. |
| **[knobs](knobs/)** | A rotary encoder or a potentiometer that reads cleanly | Encoder steps counted outside your loop so a fast spin arrives whole, and analog readings that hold still instead of jittering. |
| **[wifi](wifi/)** | WiFi that joins, retries, and reconnects by itself | One `WifiService` for both runtimes, ESP32 and Pico W alike, with callbacks when the link comes and goes. |
| **[requests](requests/)** | To fetch a URL or call a web API | A non-blocking HTTP/1.1 client.  Your LED keeps blinking while the server answers, while the body downloads, and through a timeout. |
| **[http_server](http_server/)** | To serve web pages or an API from the board | An HTTP/1.1 server with `@server.route` handlers and path parameters.  TLS where the runtime supports it; the guide has the current table. |
| **[mqtt](mqtt/)** | To talk to an MQTT broker, the message hub most home-automation setups use | An MQTT 3.1.1 client with QoS 0 and 1, last will, retain, and TLS that stays connected while the loop does everything else. |
| **[websockets](websockets/)** | A live two-way connection to a browser or a server | WebSocket client and server, plain and TLS, that can share a board with `http_server`. |
| **[sockets](sockets/)** | A raw TCP, TLS, or UDP connection | Sockets that behave the same on CircuitPython, MicroPython, and your laptop.  The layer underneath the network libraries above. |
| **[ntp](ntp/)** | Your board needs the real time of day | The time from an NTP server, close enough to UTC for TLS certificate checks and honest log timestamps. |
| **[config](config/)** | Settings your program reads on the board at startup | Typed settings with one dotted-key shape (`wifi.ssid`, `mqtt.broker.host`) that every library reads through its `<Name>Config.from_config(...)`. |
| **[kvstore](kvstore/)** | A value that survives a reboot | A small key-value store for counters, timestamps, and tokens that picks the right storage (NVM, NVS, or LittleFS) for your board. |
| **[msgpack](msgpack/)** | To send or store data more compactly than JSON | Binary serialization that reads and writes the same bytes as PyPI's `msgpack` with `use_single_float=True`. |
| **[compat](compat/)** | A standard-library piece your board's Python lacks | Small stand-ins, such as `functools.partial`, so one file of code runs everywhere. |

Tested on real boards: Raspberry Pi Pico W (RP2040) under both runtimes, and ESP32 boards from the classic, S2, and S3 families.  ESP32-C3, ESP32-C6, and RP2350 are supported chip families that have not had bench time yet.  Any other board running CircuitPython or MicroPython with at least 256 KB of RAM and 2 MB of flash (about 800 KB of it usable) is in range but has not been tested.

## Install

[The install guide](https://chumicro.com/ChuMicro/guides/install/) has the full matrix: circup on CircuitPython, mip on MicroPython, pip on your laptop, the experimental channel, and pre-compiled `.mpy` packages.  Each library's own README has a one-line install command for that library.

## Dependencies

The libraries stack from the bottom up:

- **Timing and scheduling:** `timing`, `runner`.  Most of the others build on these.
- **Physical input:** `buttons`, `knobs`.
- **Settings, storage, and serialization:** `msgpack`, `config`, `kvstore`.
- **Networking:** `wifi` joins the network, `sockets` opens TCP, TLS, and UDP connections over it, and `ntp`, `requests`, `http_server`, `websockets`, and `mqtt` speak their protocols over those sockets.

![ChuMicro library dependency graph](../support/docs/dependency-graph.svg)

Solid arrows are hard dependencies: `pip install chumicro-mqtt` brings its dependencies along.  Dashed arrows are connections your program makes when it creates the objects: you register each networked service with a `Runner`, and you hand most libraries a clock.  Those libraries never import each other; your program wires them together.

The SVG is regenerated from each library's `pyproject.toml` by [`scripts/render_dep_graph.py`](../scripts/render_dep_graph.py).
