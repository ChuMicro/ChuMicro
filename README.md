# Chumicro

Cross-runtime Python libraries for CircuitPython, MicroPython, and CPython — built for ESP32, RP2040, and other microcontrollers.

**License:** MIT · **CPython:** ≥ 3.11 · **CircuitPython:** 10.1.4 · **MicroPython:** v1.26.0

- One workspace with many individually published libraries
- Shared support packages for cross-runtime test tooling and docs assets
- CPython-first development and testing, with unix-port simulation preferred over hardware when possible
- Optional real-device validation for boards registered in a local testbed

Target runtime versions are pinned in [`target-runtimes.toml`](target-runtimes.toml). Board support tiers (Tier 1 recommended, Tier 2 constrained) are documented in [Decision 0015](plans/decisions/0015-board-architecture-support.md).

## Libraries

| Library | Description |
|---|---|
| [timing](libraries/timing/) | Wraparound-safe millisecond tick helpers, heartbeat scheduling, and deterministic test fakes. |
| [runner](libraries/runner/) | Tick-based task runner: check/handle gates, periodic tasks, shared timestamps — no async required. |
| [compat](libraries/compat/) | Cross-runtime compatibility polyfills — functools.partial and more. |
| [msgpack](libraries/msgpack/) | Compact MessagePack serialization with native CircuitPython C module delegation. |

### Which libraries do I need?

Each library solves one problem and works independently — install only what you use. Libraries fall into a few categories:

- **Timing & scheduling** — non-blocking timers, task runners, periodic polling
- **Data & serialization** — compact encoding for storage and communication
- **Runtime compatibility** — polyfills for stdlib features missing on CircuitPython/MicroPython

Browse the [documentation site](https://chumicro.github.io/ChuMicro/) for the full list with guides, or look through `libraries/` in this repo. Each library's README has installation commands, a quick example, and an API summary.

## Documentation

📖 **[Browse documentation](https://chumicro.github.io/ChuMicro/)** — all library docs, guides, and API references.

Docs are versioned per-library with [mike](https://github.com/jimporter/mike). Stable tracks tagged releases; experimental tracks `main`.

## Getting started

The prepare script works with whatever Python environment you already have — IDE-managed venv, uv, or `--create-venv` for a fresh start.  When `uv` is on PATH it is used automatically for venv creation and package installation; otherwise stdlib `venv` and `pip` are used as fallbacks.

```zsh
cd /path/to/chumicro
python scripts/prepare_workspace.py            # existing venv
python scripts/prepare_workspace.py --create-venv  # create one first
```

The script installs dev dependencies and runs lint + tests to verify. On Windows, unix-port guidance is printed automatically.

### IDE setup

**PyCharm**: shared run configurations are checked into `.idea/runConfigurations/`. After opening the project you should see play buttons for Preflight, Lint, Test, Build, and more.

**VSCode**: `.vscode/tasks.json` provides the same tasks via the Command Palette → *Tasks: Run Task*. `.vscode/settings.json` configures pytest discovery and source roots.

**No IDE**: all tasks are available from the command line via `python scripts/run.py <task>`.

### Windows

Use native Windows for editing, IDE work, linting, host-side tests, and package builds. Use WSL2 for unix-port runtime checks.

## Tasks

All tasks are run through `scripts/run.py`:

| Task | Purpose |
|---|---|
| `setup` | Install dev dependencies into the active environment |
| `lint` | Run Ruff |
| `test` | CPython tests — changed packages by default, `--all` for everything |
| `verify-examples` | Import-check all library examples |
| `docs` | Build library docs with Zensical |
| `docs --serve` | Start a live-reload docs dev server |
| `docs-preview` | Deploy docs to a local branch and serve a versioned preview |
| `docs-deploy --channel <ch>` | Deploy versioned docs to gh-pages (`experimental` or `stable`, used by CI) |
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
| `check-version` | Check VERSION bumps for changed libraries (CI gate) |
| `check-api` | Detect API breakages against the last release tag (CI gate) |

Tasks that operate on libraries (`test`, `verify-examples`, `docs`, `docs-preview`) accept `--all` or `--libraries name` to control scope. By default, `test` auto-detects changed packages.

## Distribution

Libraries are published to **[PyPI](https://pypi.org/search/?q=chumicro)** for CPython and to **bundle repos** for CircuitPython (circup) and MicroPython (mip).

| Channel | Repo | Source |
|---|---|---|
| **Stable** | [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) | tagged releases |
| **Experimental** | [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental) | `main` |

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

## Development

### Testing

- **Required:** CPython-hosted `pytest` tests with 94% coverage gate
- **Required:** MicroPython and CircuitPython unix-port cross-runtime unit tests
- **Opt-in:** real-device `functional_tests/` via `support/test_harness/` — copy `devices.example.yml` to `devices.yml` and fill in your board details

### CI & releases

PRs and pushes to `main` run the full CI suite via GitHub Actions: lint, test (CPython 3.11/3.12/3.13), verify-examples, docs-build (PRs), build, version-check, api-check, and cross-runtime compat checks.

Releases are automated. Bump a library's `VERSION` file and merge to `main` for an **experimental** release. Run the `promote.yml` workflow to create a **stable** release. Both publish to PyPI, create git tags, deploy to the appropriate bundle repo, and publish docs. See [Decision 0019](plans/decisions/0019-branching-model.md) and [Decision 0018](plans/decisions/0018-distribution-bundle-repo.md).

### Versioning

Each library has a `VERSION` file at its root — that is the single source of truth. `pyproject.toml` reads from it via hatchling's dynamic version. See [Decision 0002](plans/decisions/0002-per-library-version-files.md).

## Repository layout

```text
chumicro/
├── libraries/             # Publishable libraries (one folder each)
├── support/               # Workspace-internal packages (docs assets, test harness)
├── scripts/               # Developer tasks (run.py is the main entry point)
├── plans/                 # Roadmap, workstreams, decisions
├── .github/
│   ├── workflows/         # CI, release, promote, docs-deploy, label-sync
│   └── skills/            # Agent skill instructions
├── target-runtimes.toml   # Pinned CircuitPython/MicroPython versions
├── devices.example.yml    # Template for local board registration
└── LICENSE                # MIT
```

## Contributing

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) — it covers setup, rules, and workflow, then links to the right guide for your task:

- **[Command Line](docs/contributing/development-cli.md)**, **[PyCharm](docs/contributing/development-pycharm.md)**, or **[VS Code](docs/contributing/development-vscode.md)** — pick your environment
- **[Creating a Pull Request](docs/contributing/pull-requests.md)** — submitting your work
- **[Adding a New Library](docs/contributing/new-library.md)** — publishing your own library
- **[Releases and Promotion](docs/contributing/releases.md)** — how publishing works
- **[Working with Agents](docs/contributing/working-with-agents.md)** — using AI coding agents on this project

Contributors of all experience levels are welcome. If you're looking for a place to start, see [Good first contributions](CONTRIBUTING.md#good-first-contributions) in the contributing guide.

## Planning

See `plans/` for roadmap, workstreams, decisions, and next-up queue. The README is for users and contributors; `plans/` is the working state for agents and maintainers.
