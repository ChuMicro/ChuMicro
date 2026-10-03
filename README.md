<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

ChuMicro is a collection of small, composable Python libraries for supported MicroPython and CircuitPython boards. Use them for timed actions, WiFi connections, MQTT telemetry, HTTP requests, and HTTP routes. Your application owns its `while True` loop.

The libraries combine shared code with runtime adapters. Laptop tools and CPython host tests are separate from the code you deploy to a board.

<span id="an-led-blink-without-timesleep"></span>

<span id="install"></span>

## Choose your starting point

| Your goal | Start here |
|---|---|
| Write your first board program | Follow [Start here](docs/start-here.md). No Python experience is required. You will see the application loop, edit a counter, and observe the change. |
| Add a library to an existing project | Check [installation and board eligibility](docs/install.md), [inspect your board](docs/using-a-board.md), and choose from the [examples](docs/examples.md). |
| Build generator jobs or a library | Read [cooperative multitasking](docs/cooperative-multitasking.md), then follow [standalone integration](docs/contributing/standalone-integration.md) or [new library development](docs/contributing/new-library.md). |

<span id="sequential-work-reads-top-to-bottom"></span>

<span id="why-generators-and-not-asyncawait"></span>

## Keep control of your program

The application loop stays visible and under your control. Generators let you write jobs as sequential steps while sharing execution cooperatively with other work. If you already know generators, go directly to [the mechanism](docs/cooperative-multitasking.md) for how those jobs run together.

<span id="bring-your-own-socket-and-clock"></span>

You can also keep an existing socket, transport, or clock where a library provides a supported interface for it. MQTT is a concrete example of integrating a library with networking you already have. The [standalone integration guide](docs/contributing/standalone-integration.md) explains those interfaces and integration mechanics. The [deployment footprint guide](docs/contributing/slimming-your-deploy.md) explains how to limit what you deploy. Consult those guides for the dependencies your chosen integration needs.

<span id="give-wifi-a-deadline-and-keep-blinking"></span>

<span id="try-an-example-on-a-board"></span>

## Choose an example by task

Each example or demo centers on one primary teaching task. Start with the [task catalog](docs/examples.md), rather than treating every example as a complete application template.

<span id="a-real-project-on-one-page"></span>

<span id="watch-it-work-on-real-hardware"></span>

For a runnable networked demo, try one of these:

- [HTTP server round trip](demos/http_server_roundtrip/): change a route and observe its response.
- [MQTT sensor and motor](demos/mqtt_sensor_motor/): explore temperature telemetry, with motor PWM and LED speed commands and a sensor replacement point. MicroPython on S2 uses synthetic temperature. Other supported board and runtime combinations use CPU temperature.

For a specialized look at generators, compare the [generator-driven TCP exchange](demos/sockets_runner_connector/) with the [same exchange using explicit connection states](demos/sockets_runner_connector_explicit/). This pair focuses on how to express the connection workflow.

Without a board, use the [laptop round trip](demos/laptop_roundtrip/) for a host-only HTTP demonstration.

<span id="start-a-real-project"></span>

## Work with a board

Use [chumicro-workspace](workbench/workspace/) as the first stop for project deployment and board work. For a project starting point, see the [Workbench template](https://github.com/ChuMicro/ChuMicro-Workbench-Template).

The [board workflow](docs/using-a-board.md) covers inspecting output, state, and files. Follow the [firmware procedure](docs/troubleshooting/firmware-onto-a-new-board.md) for firmware work, and read its data-loss and recovery guidance before making changes.

For networked projects, see [runtime and project credentials](docs/wiring-wifi-credentials.md). If something fails, use [troubleshooting](docs/troubleshooting/). Detailed procedures belong in those guides, so you can follow the instructions for the operation you actually need.

<span id="the-engineering-underneath"></span>

<span id="testing"></span>

## Tests and resource costs

Tests, examples, and real-board and manual checks are part of contribution practice. CPython tests are useful host checks, not a substitute for every board check.

The [quality and resource costs page](docs/quality-and-resource-costs.md) describes the actual gates and measurement scopes, including flash budgets and selected hot-path allocation and timing baselines. Use those stated scopes when assessing results for your project. They are not blanket guarantees about every operation or every board.

<span id="contributing"></span>

## Contribute a library

Contributors can bring ideas or code, with examples, tests, and documentation developed through maintainer review. Begin with [contribution guidance](CONTRIBUTING.md) and the [new library guide](docs/contributing/new-library.md).

For accepted libraries, ChuMicro owns publication and hosting. Published versions remain available when the original author stops contributing. This preserves availability, but does not promise indefinite active maintenance.

<span id="bring-an-ai-coding-agent"></span>

## Work with an agent

An agent can help with source code, command output, tests, and board diagnosis. You select the target board and authorize changes to it.

Follow the full [agent workflow](docs/contributing/working-with-agents.md), and use [AGENTS.md](AGENTS.md) for repository instructions. Keep target selection and permission to change the board explicit when asking for help.

<span id="the-libraries"></span>

## Device libraries

Choose a library by the work you need. Each library link leads to its own documentation and API details. Use the [library dependency map](libraries/README.md) to understand relationships between packages.

| Library | Purpose |
|---|---|
| [timing](libraries/timing/) | Tick arithmetic, timers, deadlines, and periodic due checks. |
| [runner](libraries/runner/) | Service dispatch, periodic handlers, and generator jobs in an explicit application loop. |
| [buttons](libraries/buttons/) | Buttons, switches, and key matrices with debounce and press events. |
| [knobs](libraries/knobs/) | Rotary encoders, analog knobs, and input filtering. |
| [wifi](libraries/wifi/) | Connection state, retries, and reconnection. |
| [requests](libraries/requests/) | HTTP client requests. |
| [http_server](libraries/http_server/) | HTTP server and route handlers. |
| [mqtt](libraries/mqtt/) | MQTT client publishing and subscribing. |
| [websockets](libraries/websockets/) | WebSocket client and server. |
| [sockets](libraries/sockets/) | TCP and TLS connectors, listeners, and UDP. |
| [ntp](libraries/ntp/) | Network time synchronization. |
| [config](libraries/config/) | Typed settings and dotted-key access. |
| [kvstore](libraries/kvstore/) | Persistent key/value data. |
| [msgpack](libraries/msgpack/) | MessagePack encoding and decoding. |
| [compat](libraries/compat/) | Selected standard-library functionality missing from a runtime. |

<span id="bench-tools"></span>

## Laptop tools

These tools run on your laptop, not as device libraries. Start with the workspace tool unless you need a more specific operation.

| Tool | Purpose |
|---|---|
| [chumicro-workspace](workbench/workspace/) | Main entry point for projects, devices, deployment, firmware, and REPL access. |
| [chumicro-deploy](workbench/deploy/) | Lower-level probing, file transfer, and firmware operations. |
| [chumicro-repl](workbench/repl/) | Serial terminal, timed output capture, and traceback highlighting. |
| [chumicro-pytest-device](workbench/pytest-device/) | Pytest plugin for on-board test execution and host result reporting. |

<span id="documentation"></span>

## Documentation and support

Browse the [hosted documentation](https://chumicro.com/ChuMicro/) for guides, or [open an issue](https://github.com/ChuMicro/ChuMicro/issues) to report a problem or propose an improvement.

<span id="license"></span>

ChuMicro is licensed under [MIT](LICENSE).
