<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="ChuMicro" />
</p>
<h1 align="center">ChuMicro</h1>

<p align="center">
  <strong><big>Python libraries that work on your microcontroller <em>and</em> your laptop.</big></strong><br>
  <big>Write once, run on CircuitPython, MicroPython, and CPython.</big>
</p>

<p align="center">
  <a href="https://chumicro.github.io/ChuMicro/">Docs</a> •
  <a href="https://pypi.org/search/?q=chumicro">PyPI</a> •
  <a href="https://github.com/ChuMicro/ChuMicro-Bundle">Bundle</a> •
  <a href="https://github.com/ChuMicro/ChuMicro-Bundle-Experimental">Experimental</a> •
  <a href="https://github.com/ChuMicro/ChuMicro/issues">Issues</a> •
  <a href="#install">Install</a>
</p>

---

## What's in the box?

Small, focused libraries you can install independently. Use what you need.

| Library | What it does |
|---|---|
| **[timing](libraries/timing/)** | Timers that don't freeze your code — your loop keeps running while waiting. No more `time.sleep()` locking everything up. |
| **[runner](libraries/runner/)** | A simple task scheduler — register your services, call `runner.tick()` in your loop. No async needed. |
| **[compat](libraries/compat/)** | Standard library features that CircuitPython and MicroPython are missing (like `functools.partial`). |
| **[msgpack](libraries/msgpack/)** | Compact binary serialization — 30–50% smaller than JSON, great for settings and sensor data. |

Works on ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico), STM32, and most boards with at least 256 KB RAM and 4 MB flash. Browse the [documentation site](https://chumicro.github.io/ChuMicro/) for guides and API references, or look through `libraries/` — each library's README has install commands, a quick example, and an API summary.

<details>
<summary>Which libraries do I need? (dependencies and selection guide)</summary>

### Dependencies

```
runner → timing
timing    (no dependencies)
compat    (no dependencies)
msgpack   (no dependencies)
```

### Start with the problem you're solving

- **"I need timers that don't freeze my loop"** → [timing](libraries/timing/)
- **"I have multiple things happening in my loop"** → [runner](libraries/runner/) (includes timing)
- **"I need to store settings or send data compactly"** → [msgpack](libraries/msgpack/)
- **"functools.partial doesn't exist on my board"** → [compat](libraries/compat/)

</details>

## Install

Pick the install method for your runtime — swap `chumicro-timing` for whichever library you need.

> **A note on naming:** pip uses hyphens (`chumicro-timing`); the import name and bundle path use underscores (`chumicro_timing`). That's standard across the Python ecosystem — PyPI uses hyphens by convention, but Python import names must be valid identifiers. Copy commands from the blocks below as-is.

**CircuitPython ([circup](https://github.com/adafruit/circup)):**

circup is CircuitPython's package manager — it uses [bundles](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup/bundle-commands) to find third-party packages. Register the ChuMicro bundle once, then install any library by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

**MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html)):**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

Or from the REPL on a network-capable board:

```python
import mip
mip.install("github:ChuMicro/ChuMicro-Bundle/chumicro_timing")
```

> **Want pre-compiled `.mpy` bytecode?** Add `mpy6/` before the package name for faster startup and lower RAM usage on boards with mpy format v6 (MicroPython 1.24+):
> ```
> mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
> ```

**CPython (pip):**

On your laptop, install from PyPI — no bundle needed:

```bash
pip install chumicro-timing
```

*New here? The install commands above are all you need — the experimental-builds section below is only for users who want to track pre-release versions.*

<details>
<summary>Experimental (pre-release) builds and channel switching</summary>

Pre-release builds are published automatically when a library version is bumped. Do not register both bundles simultaneously — circup may pick either version for a given package.

```bash
# CircuitPython — switch to experimental
circup bundle-remove ChuMicro/ChuMicro-Bundle              # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-timing

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing

# CPython
pip install chumicro-timing-experimental
```

| Channel | Bundle repo | Source |
|---|---|---|
| **Stable** | [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) | tagged releases |
| **Experimental** | [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental) | `main` |

</details>

## Your first program

A blink that doesn't freeze — the embedded hello world:

```python
from chumicro_timing import Heartbeat, ticks_ms

heartbeat = Heartbeat(period_ms=1000)

while True:
    now = ticks_ms()
    if heartbeat.poll(now):
        print("one second elapsed")  # or: led.value = not led.value
```

Or try it in the REPL:

```python
>>> from chumicro_timing import ticks_ms
>>> ticks_ms()
42387
```

## Documentation

📖 **[Browse the docs](https://chumicro.github.io/ChuMicro/)** — guides, API references, and examples for every library.

Each library has its own docs with a version selector so you can switch between stable and experimental (dev).

## Contributing

We welcome contributors of all experience levels. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, guidelines, and how to submit a pull request. Want the short version? Check the [contributor cheat sheet](docs/contributing/cheat-sheet.md). Not sure where to start? Check out [good first contributions](CONTRIBUTING.md#good-first-contributions).

If you use PyCharm, note that choosing or changing the project interpreter may rewrite `.idea/chumicro.iml`. The file is tracked in git so source roots stay in sync across contributors — click the **Sync IDE** run configuration (or run `python scripts/run.py sync-ide`) to restore the managed source-root layout before committing. `python scripts/run.py setup` and `python scripts/prepare_workspace.py` do the same regeneration as part of their normal workflow.

If you want to work on real-board validation or IDE-driven `functional_tests/`, start with the [device testing guide](docs/contributing/device-testing.md). It documents how `python scripts/run.py setup` generates `devices.yml` and `device-config.yml`, how bare `python scripts/run.py test-device` uses the `defaults:` section in `devices.yml`, and how PyCharm / VS Code route explicit `functional_tests/` targets through the device pytest plugin.

### Development quick links

- [Contributor cheat sheet](docs/contributing/cheat-sheet.md)
- [Device testing](docs/contributing/device-testing.md)
- [PyCharm guide](docs/contributing/development-pycharm.md)
- [VS Code guide](docs/contributing/development-vscode.md)
- [Other editors / CLI guide](docs/contributing/development-other-editors.md)

## Repository layout

```text
chumicro/
├── libraries/             # Publishable libraries (one folder each)
├── support/               # Internal packages (docs assets, test harness)
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
