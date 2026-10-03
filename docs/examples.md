---
title: "ChuMicro examples: run, change, and understand a program"
---

Choose to [run a program](#run-a-program), [change a working program](#change-a-working-program), or [understand how work shares a loop](#understand-how-work-shares-a-loop). These are independent entry points, not a required sequence. You can select a program without hardware. Check its prerequisites here, then follow its linked instructions to run it.

## Prepare for your choice

Follow [Repository setup](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md#setting-up) before executing repository programs. Library examples live under `libraries/<library>/examples/`, and demos under `demos/<name>/`. These checkout files are separate from your workbench sources.

Library links open complete source files. Use the shared deployment recipe below and any configuration notes in the selected file. Board demos require a repository checkout and include complete programs, laptop drivers, and READMEs. Use each demo’s README for its setup and execution instructions. The laptop demo is app-only.

For board execution, install matching MicroPython or CircuitPython firmware and select a target with saved registration. Network programs also need [WiFi credentials](wiring-wifi-credentials.md) and a reachable peer.

> **Warning:** Deployment is clean-slate by default. It removes board files outside the payload and keep set (`boot.py`, `boot_out.txt`, `_chu_kv.msgpack`). Back up wanted board-only files first. See [Deployment and file persistence](troubleshooting/deploys-and-file-persistence.md) for persistence and recovery guidance.

From a laptop terminal at the prepared repository root, with the virtual environment active, use:

```bash
chumicro-workspace deploy-example timing rate_blink --device <device-id>
```

Replace `<device-id>` with your saved device name before execution. The positional arguments are the library folder and example filename without `.py`. Thus `timing/rate_blink.py` becomes `timing rate_blink`, `timing/multiple_rates.py` becomes `timing multiple_rates`, and `runner/generator_basic.py` becomes `runner generator_basic`. The same rule applies to other library examples.

The new program starts after deployment. A normal interactive invocation opens the serial REPL. To change an example, edit the selected laptop source file, save, and repeat the deployment command.

## Run a program

For your first board project, follow [Start here](start-here.md). It provides a complete program with a visible `while True` loop. Make the loop-counter edit and redeploy to observe its effect.

For a console result without LED setup, choose [Console heartbeat](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/rate_blink.py). `rate_blink.py` sets up `Rate(1000, ticks_ms())` and has a visible `while True` loop. Expect recurring `beat!` output. It does not initialize an LED.

To blink a physical LED instead, select the file for your runtime and confirm that its pin matches your board.

| Result | Complete program | Essential prerequisite |
|---|---|---|
| Blink with CircuitPython | [CircuitPython LED](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/circuitpython_blink.py) | CircuitPython board with the intended LED available through `board.LED` and `digitalio`. |
| Blink with MicroPython | [MicroPython LED](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/micropython_blink.py) | MicroPython board whose intended LED uses `Pin(2)` as supplied, or a corrected pin selection. |

For the heartbeat or either LED program, make your next edit an interval change, then redeploy and observe the new cadence.

## Change a working program

Pick the timing pattern or exchange you need, then change one behavior.

| Result and complete program | Observe, then change | Essential prerequisite |
|---|---|---|
| Keep independent intervals with [Several timers](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/timing/examples/multiple_rates.py) | `multiple_rates.py` uses 200, 1000, and 5000 ms periods with one timestamp per loop. Change one period and its printed label, retaining the other schedules. | Board with matching firmware. |
| Adapt [HTTP server round trip](https://github.com/ChuMicro/ChuMicro/tree/main/demos/http_server_roundtrip) | `/hello` returns JSON that the laptop driver prints. Change the message value, rerun the driver, and inspect the changed JSON. | Board and laptop on a reachable LAN. |
| Adapt [MQTT sensor and motor](https://github.com/ChuMicro/ChuMicro/tree/main/demos/mqtt_sensor_motor) | Telemetry runs every 2000 ms, with `0-100` speed commands. Change the cadence or `read_celsius()` input. | Mosquitto and reachable network peers. No motor is needed for a bench run. |

The MQTT demo uses a digital LED on Pico W and a PWM LED on Lolin S2 mini. MicroPython on the S2 uses synthetic temperature.

## Understand how work shares a loop

You can start here without completing an earlier example. [Generator deadlines](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/runner/examples/generator_basic.py) is the smallest introduction. In `generator_basic.py`, follow the ordered prints around 500 and 1000 ms deadline waits. Its finite loop ends when `handle.done` indicates completion. No socket or network setup is needed.

Then compare the two TCP implementations side by side.

| Learning task | What to trace | Essential prerequisite |
|---|---|---|
| Follow [TCP generator](https://github.com/ChuMicro/ChuMicro/tree/main/demos/sockets_runner_connector) | In `sockets_runner_connector`, `echo_run` connects, sends, receives, and cleans up its socket in `finally`. A periodic heartbeat shares execution, with `while True` after registration. | WiFi board and reachable laptop. For CircuitPython, apply the owning README’s socket-mode correction for cooperative sending and receiving. |
| Compare [TCP service comparison](https://github.com/ChuMicro/ChuMicro/tree/main/demos/sockets_runner_connector_explicit) | `sockets_runner_connector_explicit` performs the same echo exchange through `EchoService`, `check`, `handle`, and socket-interest methods. | WiFi board and reachable laptop. Read alongside the generator version. |

For message consumption, inspect [MQTT receive stream](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/mqtt/examples/receive_stream.py). `receive_stream.py` registers the client and consumer separately and uses `yield from mqtt.next_message()`. It needs a configured broker and a message publisher. Complete WiFi setup before the runner loop.

`yield from` delegates execution. Suspension occurs only when the delegated code yields. See [Cooperative multitasking](cooperative-multitasking.md) for the scheduling explanation.

Without hardware, choose [Laptop round trip](https://github.com/ChuMicro/ChuMicro/tree/main/demos/laptop_roundtrip). `laptop_roundtrip` is a finite CPython demonstration with a loopback HTTP server and client and printed LED state. It needs neither a board nor an external network.

For standalone MQTT integration with dependencies you supply, read [Supply your own dependencies](contributing/standalone-integration.md). For implementation work, continue to [Write a library](contributing/new-library.md) and [Quality and resource costs](quality-and-resource-costs.md).

## Find other programs or inspect a board

Browse [All libraries](https://github.com/ChuMicro/ChuMicro/tree/main/libraries) and [All demos](https://github.com/ChuMicro/ChuMicro/tree/main/demos) for other complete artifacts. Their READMEs or source docstrings own the wiring, broker setup, and protocol details.

For board output, REPL interaction and exit instructions, or file inspection, use [Inspect a running board and its files](using-a-board.md).
