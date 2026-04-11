<p align="center">
  <img src="support/docs/chumicro.png" width="420" alt="Chumicro" />
</p>
<h1 align="center">Chumicro</h1>

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
  <a href="#get-started">Get Started</a>
</p>

---

## What's in the box?

Small, focused libraries you can install independently. Use what you need.

| Library | What it does |
|---|---|
| **[timing](libraries/timing/)** | Non-blocking timers that handle millisecond wraparound for you. No more `time.sleep()` freezing your loop. |
| **[runner](libraries/runner/)** | A simple task scheduler — register your services, call `runner.tick()` in your loop. No async needed. |
| **[compat](libraries/compat/)** | Standard library features that CircuitPython and MicroPython are missing (like `functools.partial`). |
| **[msgpack](libraries/msgpack/)** | Compact binary serialization — 30–50% smaller than JSON, great for settings and sensor data. |

### Supported boards

Works on ESP32 (S2, S3, C3, C6), RP2040/RP2350 (Raspberry Pi Pico), STM32, and most boards with at least 256 KB RAM and 4 MB flash.

### Dependencies

```
runner → timing
timing    (no dependencies)
compat    (no dependencies)
msgpack   (no dependencies)
```

### Which libraries do I need?

Start with the problem you're solving:

- **"I need non-blocking timers"** → [timing](libraries/timing/)
- **"I have multiple things happening in my loop"** → [runner](libraries/runner/) (includes timing)
- **"I need to store settings or send data compactly"** → [msgpack](libraries/msgpack/)
- **"functools.partial doesn't exist on my board"** → [compat](libraries/compat/)

Browse the [documentation site](https://chumicro.github.io/ChuMicro/) for guides and API references, or look through `libraries/` — each library's README has install commands, a quick example, and an API summary.

## Get started

Pick the install method for your runtime — swap `chumicro-timing` for whichever library you need.

**CircuitPython ([circup](https://github.com/adafruit/circup)):**

circup is CircuitPython's package manager — it uses bundles to find third-party packages. Register the ChuMicro bundle once, then install any library by name:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

**MicroPython ([mip](https://docs.micropython.org/en/latest/reference/packages.html)):**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

**CPython (pip):**

```bash
pip install chumicro-timing
```

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

### Your first program

A non-blocking blink — the embedded hello world:

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

## Development

### Setup

Want to hack on Chumicro itself? The setup script gets you from clone to working in one command:

```zsh
git clone https://github.com/ChuMicro/ChuMicro.git
cd ChuMicro
python scripts/prepare_workspace.py --create-venv
```

The script creates a virtualenv, installs everything, and runs lint + tests to verify. When you see `Workspace is ready`, you're good. If you already have a venv activated, drop `--create-venv`.

When `uv` is on PATH it's used automatically for faster installs; otherwise stdlib `venv` and `pip` are used as fallbacks.

### IDE setup

The workspace generates configurations for popular editors automatically:

- **PyCharm** — shared run configs in `.idea/runConfigurations/` (Preflight, Lint, Test, Build, etc.)
- **VS Code** — `.vscode/tasks.json` for Command Palette → *Tasks: Run Task*
- **Neovim, Zed, Emacs, Sublime** — `pyrightconfig.json` at the root gives any Pyright-based LSP full import resolution
- **Any terminal** — all tasks are available via `python scripts/run.py <task>`

See the [contributing guide](CONTRIBUTING.md#development-environment) for full setup instructions for your editor.

### Windows

Use native Windows for editing, linting, tests, and builds. Use WSL2 for unix-port runtime checks (MicroPython/CircuitPython simulation).

### Tasks

Everything goes through one command: `python scripts/run.py <task>`.

| Task | What it does |
|---|---|
| `setup` | Install dev dependencies |
| `lint` | Check code style (Ruff) |
| `test` | Run CPython tests (changed packages by default, `--all` for everything) |
| `test-scripts` | Run infrastructure tests for `scripts/` |
| `verify-examples` | Check that example scripts parse and import correctly |
| `docs` | Build library documentation |
| `docs --serve` | Start a live-reload docs dev server |
| `docs-preview` | Deploy docs locally and serve a versioned preview |
| `build` | Build distributable packages |
| `preflight` | **The big one** — runs everything CI will run. Do this before pushing. |
| `new-library <name>` | Scaffold a new library |
| `sync-ide` | Regenerate IDE configs from workspace structure |

<details>
<summary>More tasks (CI, cross-runtime, deployment)</summary>

| Task | What it does |
|---|---|
| `docs-deploy --channel <ch>` | Deploy versioned docs to gh-pages (CI) |
| `prepare-micropython` | Build the pinned MicroPython unix-port binary |
| `prepare-circuitpython` | Build the pinned CircuitPython unix-port binary |
| `test-micropython-compatibility` | Cross-runtime tests under MicroPython |
| `test-circuitpython-compatibility` | Cross-runtime tests under CircuitPython |
| `test-runtime-matrix` | Test all packages on all three runtimes |
| `test-device` | Manual device validation placeholder |
| `check-version` | Verify VERSION bumps for changed libraries (CI gate) |
| `check-api` | Detect API breakages against last release (CI gate) |

</details>

Tasks that operate on libraries (`test`, `verify-examples`, `docs`, `docs-preview`) accept `--all` or `--libraries name` to control scope. By default, `test` auto-detects changed packages.

### Testing

- **CPython tests** — pytest with a 94% branch coverage gate per library
- **Cross-runtime** — MicroPython and CircuitPython unix-port unit tests
- **On-device** — opt-in `functional_tests/` via `support/test_harness/` (copy `devices.example.yml` to `devices.yml`)

### CI & releases

PRs and pushes to `main` run the full suite: lint, test (CPython 3.11/3.12/3.13), verify-examples, docs, build, version-check, api-check, and cross-runtime compat.

Releases are automated — bump a library's `VERSION` file and merge for an **experimental** release. Run `promote.yml` for **stable**. Both publish to PyPI, create tags, deploy bundles, and publish docs. See [Decision 0019](plans/decisions/0019-branching-model.md) and [Decision 0018](plans/decisions/0018-distribution-bundle-repo.md).

### Versioning

Each library has a `VERSION` file — that's the single source of truth. [Semantic versioning](https://semver.org/). See [Decision 0002](plans/decisions/0002-per-library-version-files.md).

## Repository layout

```text
chumicro/
├── libraries/             # Publishable libraries (one folder each)
├── support/               # Internal packages (docs assets, test harness)
├── scripts/               # Developer tasks (run.py is the entry point)
├── plans/                 # Roadmap, decisions, session logs
├── .github/
│   ├── workflows/         # CI, release, promote, docs-deploy
│   └── skills/            # Agent skill instructions
├── target-runtimes.toml   # Pinned runtime versions
├── devices.example.yml    # Template for local board registration
└── LICENSE                # MIT
```

## Contributing

We welcome contributors of all experience levels. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup, guidelines, and how to submit a pull request. Not sure where to start? Check out [good first contributions](CONTRIBUTING.md#good-first-contributions).

## License

[MIT](LICENSE)
