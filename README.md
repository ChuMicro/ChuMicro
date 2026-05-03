<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Microcontroller code that doesn't freeze.</big></strong><br>
  <big>Your LED keeps blinking through wifi reconnect, TLS handshake, slow HTTP, stalled MQTT.</big><br>
  <big>Cross-runtime: CircuitPython, MicroPython, CPython.</big>
</p>

<p align="center">
  <a href="https://chumicro.github.io/ChuMicro/">Docs</a> •
  <a href="https://github.com/ChuMicro/ChuMicro-Workspace-Template">Workspace template</a> •
  <a href="libraries/">Libraries</a> •
  <a href="workbench/">Workbench tools</a> •
  <a href="https://github.com/ChuMicro/ChuMicro/issues">Issues</a>
</p>

---

## Eight lines, no freeze

```python
from chumicro_timing import Heartbeat, ticks_ms

heartbeat = Heartbeat(period_ms=500)

while True:
    if heartbeat.poll(ticks_ms()):
        print("blink")  # or toggle an LED here
    # ... add wifi, sockets, MQTT here — the print/LED keeps cadence ...
```

Drop that on a CircuitPython or MicroPython board (or paste it into Python on your laptop) and the print fires every 500 ms forever.  The loop runs hundreds of times per second between prints, ready for whatever else you want to do.

**Why it matters.**  Every networked service ChuMicro ships — `chumicro-wifi`, `chumicro-sockets`, `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets` — is the same shape: `check(now_ms) -> bool` + `handle(now_ms)`.  Register as many as you need with [`chumicro-runner`](libraries/runner/).  Every state change is visible from `print()` on the serial console; nothing hides inside an event loop.  We picked tick-based scheduling because transparent state matters more than syntactic concurrency on a board where serial output is your only window.

<details>
<summary>How to actually blink an LED (per-runtime GPIO)</summary>

CircuitPython:
```python
import board, digitalio
led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
# inside the `if heartbeat.poll(...):` block:
led.value = not led.value
```

MicroPython (board pin number varies):
```python
from machine import Pin
led = Pin(2, Pin.OUT)
# inside the `if heartbeat.poll(...):` block:
led.value(not led.value())
```
</details>

## Install

```bash
# CircuitPython (via circup)
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing

# MicroPython (via mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# CPython (via pip)
pip install chumicro-timing
```

For pre-compiled `.mpy` bundles, the experimental channel, and the full install matrix, see [`INSTALL.md`](INSTALL.md).

## Now what?

| | |
|---|---|
| **Want a real project layout?** | [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) — clone-and-go.  Safer than editing `code.py` directly on the device (no FAT-filesystem wear, no losing files when the CIRCUITPY drive hiccups).  Recommended even for a single-project board. |
| **Want more libraries?** | [`libraries/`](libraries/) — wifi, mqtt, sockets, requests, http_server, websockets, ntp, kvstore, config, msgpack, runner, events, logging, compat. |
| **Want host-side tools?** | [`workbench/`](workbench/) — `chumicro-deploy`, `chumicro-repl`, `chumicro-workspace`, `chumicro-pytest-device`. |
| **Want to build your own?** | [`CONTRIBUTING.md`](CONTRIBUTING.md) — scaffold one with `python scripts/run.py new-library`. |

## Documentation

📖 **[chumicro.github.io/ChuMicro](https://chumicro.github.io/ChuMicro/)** — guides, API references, and examples for every library.  Each library has its own docs with a version selector so you can switch between stable and experimental.

## Repository layout

```text
chumicro/
├── libraries/             # Publishable libraries that run on microcontrollers (CP + MP + CPython)
├── workbench/             # Publishable host-only tools that run on your laptop (CPython only)
├── support/               # Internal packages (docs assets, test harness) — never published
├── scripts/               # Developer tasks (run.py is the entry point)
├── docs/contributing/     # Style guide, cheat sheet, setup guides
├── plans/                 # Roadmap, decisions, design history
├── .github/
│   ├── workflows/         # CI, release, promote, docs-deploy
│   └── skills/            # Agent skill instructions
├── target-runtimes.toml   # Pinned runtime versions
└── LICENSE                # MIT
```

## License

[MIT](LICENSE)
