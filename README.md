# Chumicro

Chumicro is a mono-workspace for Python libraries that run across CPython, MicroPython, and CircuitPython.

- One workspace with many individually published libraries
- Shared support packages for runtime detection, mocks, and test tooling
- CPython-first development and testing, with unix-port simulation preferred over hardware when possible
- Optional real-device validation for boards registered in a local testbed

## Libraries

| Library | Description |
|---|---|
| [timing](libraries/timing/) | Cross-runtime millisecond tick helpers, wraparound-safe arithmetic, and heartbeat scheduling. Works on CPython, MicroPython, and CircuitPython. |

## Developer workflow

1. Write or update code against a small public API and runtime shims
2. Run host-side tests on CPython
3. Run compatibility checks for MicroPython and CircuitPython
4. Run on-device tests only for behavior that mocks cannot prove

## Testing model

- **Required**: CPython-hosted `pytest` tests with coverage (90%+ gate)
- **Advisory**: MicroPython and CircuitPython unix-port smoke tests
- **Opt-in**: real-device `device_tests/` run through the Chumicro test harness

## Repository shape

```text
chumicro/
├── scripts/               # User-facing commands (prepare, run tasks)
├── ci/                    # CI-internal plumbing (compile scripts, smoke runners)
├── plans/                 # Roadmap, workstreams, decisions, and prompts
│   ├── decisions/
│   ├── prompts/
│   └── workstreams/
├── support/
│   ├── runtime/           # Cross-runtime detection helpers (workspace-internal)
│   └── test_harness/      # Lightweight on-device test runner (workspace-internal)
├── libraries/
│   └── timing/            # Cross-runtime timing library
│       ├── src/
│       ├── tests/
│       ├── device_tests/
│       ├── docs/          # ReadTheDocs content
│       └── examples/      # Usage examples
├── devices.example.yml    # Template for local board registration
└── .github/workflows/     # CI
```

## Getting started

The prepare script works with whatever Python environment you already have — IDE-managed venv, uv, conda, or system Python:

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

**PyCharm**: shared run configurations are checked into `.idea/runConfigurations/`. After opening the project you should see play buttons for Preflight, Lint, Test, Build, MicroPython Compat, CircuitPython Compat, and Runtime Matrix.

**VSCode**: `.vscode/tasks.json` provides the same tasks via the Command Palette → *Tasks: Run Task*. `.vscode/settings.json` configures pytest discovery and source roots.

**No IDE**: all tasks are available from the command line via `python scripts/run.py <task>`.

## Tasks

All tasks are run through `scripts/run.py`:

| Task | Purpose |
|---|---|
| `setup` | Install dev dependencies into the active environment |
| `lint` | Run Ruff |
| `test` | Run pytest with coverage |
| `verify-examples` | Import-check all library examples |
| `docs` | Build library docs with MkDocs |
| `build` | Build all publishable package distributions |
| `preflight` | Run all required CI checks (lint + test + build) |
| `prepare-micropython` | Build the pinned MicroPython unix-port binary under `.tools/` |
| `prepare-circuitpython` | Build the pinned CircuitPython unix-port binary under `.tools/` |
| `test-micropython-compat` | Smoke test under MicroPython (auto-prepares if needed) |
| `test-circuitpython-compat` | Smoke test under CircuitPython (auto-prepares if needed) |
| `test-runtime-matrix` | Run host tests + MicroPython + CircuitPython compat |
| `test-device` | Manual device validation placeholder |

## Platform switching

The repo switches runtimes by running the same library code under different interpreters. The compat tasks auto-prepare the unix-port binaries if they are not already built.

## Device validation

Real-board execution is manual-only. Copy `devices.example.yml` to `devices.yml` and fill in your board details. Use `libraries/timing/device_tests/` with `support/test_harness/` on the target board.

## Versioning

Each library has a `VERSION` file at its root — that is the single source of truth. `pyproject.toml` reads from it via setuptools `dynamic` version. See [Decision 0002](plans/decisions/0002-per-library-version-files.md).

## Planning

See `plans/` for roadmap, workstreams, decisions, and next-up queue. The README is for users and contributors; `plans/` is the working state for agents and maintainers.

