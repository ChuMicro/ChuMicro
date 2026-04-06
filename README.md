# Chumicro

Cross-runtime Python libraries for CircuitPython, MicroPython, and CPython — built for ESP32, RP2040, and other microcontrollers.

📖 **[Documentation site](https://chumicro.github.io/ChuMicro/)** — browse all library docs, guides, and API references.

- One workspace with many individually published libraries
- Shared support packages for runtime detection, mocks, and test tooling
- CPython-first development and testing, with unix-port simulation preferred over hardware when possible
- Optional real-device validation for boards registered in a local testbed

## Libraries

| Library | Description |
|---|---|
| [timing](libraries/timing/) | Wraparound-safe millisecond tick helpers, heartbeat scheduling, and deterministic test fakes. |
| [runner](libraries/runner/) | Tick-based task runner: check/handle gates, periodic tasks, shared timestamps — no async required. |
| [compat](libraries/compat/) | Cross-runtime compatibility polyfills — functools.partial and more. |
| [msgpack](libraries/msgpack/) | Compact MessagePack serialization with native CircuitPython C module delegation. |

## Documentation

📖 Docs are published per-library with a version selector powered by [mike](https://github.com/jimporter/mike):

| Library | Stable | Experimental |
|---|---|---|
| timing | [stable](https://chumicro.github.io/ChuMicro/timing/stable/) | [experimental](https://chumicro.github.io/ChuMicro/timing/experimental/) |
| runner | [stable](https://chumicro.github.io/ChuMicro/runner/stable/) | [experimental](https://chumicro.github.io/ChuMicro/runner/experimental/) |
| compat | [stable](https://chumicro.github.io/ChuMicro/compat/stable/) | [experimental](https://chumicro.github.io/ChuMicro/compat/experimental/) |
| msgpack | [stable](https://chumicro.github.io/ChuMicro/msgpack/stable/) | [experimental](https://chumicro.github.io/ChuMicro/msgpack/experimental/) |

Stable tracks `main` (released versions).  Experimental tracks `develop` (pre-release).

## Distribution

Libraries are published to **PyPI** for CPython and to **bundle repos** for CircuitPython (circup) and MicroPython (mip).

| Channel | Repo | Branch |
|---|---|---|
| **Stable** | [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) | `main` |
| **Experimental** | [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental) | `develop` |

Install with circup (remove the other channel first if switching):

```bash
circup bundle-remove ChuMicro/ChuMicro-Bundle-Experimental   # skip if never added
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

Install with mip:

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

Install with pip (CPython):

```bash
pip install chumicro-timing
```

## Developer workflow

1. Write or update code against a small public API and runtime shims
2. Run host-side tests on CPython
3. Run compatibility checks for MicroPython and CircuitPython
4. Run functional tests only for behavior that mocks cannot prove

## Testing model

- **Required**: CPython-hosted `pytest` tests with coverage (90%+ gate)
- **Advisory**: MicroPython and CircuitPython unix-port cross-runtime unit tests
- **Opt-in**: real-device `functional_tests/` run through the Chumicro test harness

## Repository shape

```text
chumicro/
├── scripts/               # User-facing commands (prepare, run tasks)
├── plans/                 # Roadmap, workstreams, decisions, and prompts
│   ├── decisions/
│   ├── prompts/
│   └── workstreams/
├── support/
│   ├── runtime/           # Cross-runtime detection helpers (workspace-internal)
│   └── test_harness/      # Lightweight cross-runtime test runner (workspace-internal)
├── libraries/
│   ├── timing/            # Cross-runtime timing library
│   ├── runner/            # Tick-based task runner
│   ├── compat/            # Compatibility polyfills
│   └── msgpack/           # MessagePack serialization
├── devices.example.yml    # Template for local board registration
└── .github/workflows/     # CI
```

## Getting started

The prepare script works with whatever Python environment you already have — IDE-managed venv, uv, or `--create-venv` for a fresh start.  When `uv` is on PATH it is used automatically for venv creation and package installation; otherwise stdlib `venv` and `pip` are used as fallbacks.

```zsh
cd /path/to/chumicro
python scripts/prepare_workspace.py
```

If you don't have an environment yet, pass `--create-venv` to create one:

```zsh
python scripts/prepare_workspace.py --create-venv
```

The script installs dev dependencies and runs lint + tests to verify. On Windows, unix-port guidance is printed automatically.

### Windows

Use native Windows for editing, IDE work, linting, host-side tests, and package builds. Use WSL2 for unix-port runtime checks.

### IDE setup

**PyCharm**: shared run configurations are checked into `.idea/runConfigurations/`. After opening the project you should see play buttons for Preflight, Lint, Test, Build, Verify Examples, Docs, MicroPython Compat, CircuitPython Compat, and Runtime Matrix.

**VSCode**: `.vscode/tasks.json` provides the same tasks via the Command Palette → *Tasks: Run Task*. `.vscode/settings.json` configures pytest discovery and source roots.

**No IDE**: all tasks are available from the command line via `python scripts/run.py <task>`.

## Tasks

All tasks are run through `scripts/run.py`:

| Task | Purpose |
|---|---|
| `setup` | Install dev dependencies into the active environment |
| `lint` | Run Ruff |
| `test` | CPython tests — changed packages by default, `--all` for everything |
| `verify-examples` | Import-check all library examples |
| `docs` | Build library docs with Zensical |
| `build` | Build all publishable package distributions |
| `preflight` | Full CI gate: lint + test all + examples + compat + build |
| `new-library <name>` | Scaffold a new library and regenerate IDE configs |
| `sync-ide` | Regenerate PyCharm and VS Code configs from workspace structure |
| `prepare-micropython` | Build the pinned MicroPython unix-port binary under `.tools/` |
| `prepare-circuitpython` | Build the pinned CircuitPython unix-port binary under `.tools/` |
| `test-micropython-compatibility` | Cross-runtime unit tests under MicroPython (auto-prepares if needed) |
| `test-circuitpython-compatibility` | Cross-runtime unit tests under CircuitPython (auto-prepares if needed) |
| `test-runtime-matrix` | Test all packages on CPython + MicroPython + CircuitPython |
| `test-device` | Manual device validation placeholder |

## Platform switching

The repo switches runtimes by running the same library code under different interpreters. The compat tasks auto-prepare the unix-port binaries if they are not already built.

## Device validation

Real-board execution is manual-only. Copy `devices.example.yml` to `devices.yml` and fill in your board details. Use `libraries/timing/functional_tests/` with `support/test_harness/` on the target board.

## Versioning

Each library has a `VERSION` file at its root — that is the single source of truth. `pyproject.toml` reads from it via hatchling's dynamic version. See [Decision 0002](plans/decisions/0002-per-library-version-files.md).

## Planning

See `plans/` for roadmap, workstreams, decisions, and next-up queue. The README is for users and contributors; `plans/` is the working state for agents and maintainers.

