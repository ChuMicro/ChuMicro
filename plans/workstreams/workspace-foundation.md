# Workstream: Workspace Foundation

Status: `done`

## Purpose

Define the repo layout, shared tooling, and local developer ergonomics for a Python mono-workspace that works well in PyCharm and supports many individually published libraries.

## Scope

- root repository layout
- shared lint, test, and coverage configuration
- local development workflow
- PyCharm-friendly conventions
- support package structure under `support/`
- shared commands or task entrypoints for humans and agents

## Initial deliverables

- root `README.md`
- root `.gitignore`
- root `pyproject.toml`
- first reusable support package
- first GitHub Actions CI workflow

## Current verified deliverables

- root `README.md`, `.gitignore`, and `pyproject.toml` exist
- `support/runtime/` exists as the first reusable support package
- `support/test_harness/` exists as the first tiny on-device runner scaffold
- `libraries/timing/` exists as the first publishable package slice under `libraries/`
- `libraries/serviceable/` exists as the second publishable library (scaffolded via `new-library`)
- `.github/workflows/ci.yml` exists and uses the shared repo task entrypoints
- `scripts/run.py` exists as the current shared task interface for humans, agents, and CI
- `scripts/run.py` auto-discovers all libraries and support packages (no hard-coded lists)
- `scripts/run.py` provides scoped test running: `--all`, `--libraries`, branch-diff detection, `-k lib/test`/`-x`/`-v`/`--no-cov`
- `scripts/run.py new-library <name>` scaffolds a new library and regenerates IDE configs
- `scripts/run.py sync-ide` generates `.idea/chumicro.iml` (PyCharm) and `pyrightconfig.json` (VS Code)
- Root `conftest.py` auto-discovers source roots and excludes `functional_tests/`
- Per-library pytest runs avoid test-directory collisions (Decision 0009)
- `scripts/prepare_micropython.py` and `scripts/prepare_circuitpython.py` provide unix-port preparation
- `support/test_harness/run_cross_runtime.py` exists as the canonical cross-runtime test runner entrypoint (Decision 0016)
- `.github/workflows/ci.yml` now includes advisory runtime compatibility jobs in addition to the required host lane
- `devices.example.yml` exists as the first committed local device template

## Developer modes

The workspace should support three explicit modes:

### 1. CPython host mode

Primary use:

- daily development
- linting
- packaging
- host-side unit tests
- IDE indexing and refactoring

This mode should be the default path for both humans and agents.

### 2. MicroPython target mode

Primary use:

- compatibility validation
- cross-runtime unit tests
- selected on-device tests

This mode should avoid direct dependency on CPython-only libraries and should exercise the same public library API whenever possible.

### 3. CircuitPython target mode

Primary use:

- compatibility validation
- cross-runtime unit tests
- selected on-device tests on mounted boards or via a transport tool

This mode should validate the same public API while allowing a small shim for platform-specific modules.

## Platform switching model

Developers should not manually rewrite imports or edit files to switch platforms.

Instead, switching should happen through:

- runtime detection in shared shim code
- dependency injection for hardware-facing pieces
- separate test layers for host logic, compatibility checks, and device execution
- one shared task interface for common actions such as `test`, `test-micropython-compat`, `test-circuitpython-compat`, and `test-device`

Current verified implementation:

- the shared task interface lives in `scripts/run.py`
- CI uses the same task interface for lint, host tests, package builds, and advisory runtime compatibility jobs
- compatibility and device commands exist now as honest scaffolding entrypoints rather than hidden future intent

## Tooling direction

Current verified state:

- `uv` auto-detected and preferred for venv creation and package installation; stdlib `venv` + `pip` as fallback
- `pytest`
- `pytest-cov`
- `ruff`
- `scripts/run.py` as the permanent repo-level task runner

`scripts/run.py` is the long-term task runner for humans, agents, and CI.  It handles library discovery, scoped testing, scaffolding, IDE config generation, and cross-runtime compatibility orchestration — none of which `uv` replaces.  `uv` is a fast package installer and environment manager; when it is on PATH, `prepare_workspace.py` and `run.py setup` auto-detect it and prefer it over `pip`/stdlib `venv`.  When uv is not available, the workspace falls back to `pip` and stdlib `venv` transparently.

Current decision:

- `uv` is auto-detected and preferred when available; `pip`/`venv` are the fallback
- `scripts/run.py` stays as the task runner regardless of which installer is used

## PyCharm and agent ergonomics

- mark package `src/` folders as source roots
- keep package layout predictable across libraries
- centralize runtime detection and shared mocks so agents do not need to rediscover them in each package
- avoid hidden local setup that only works on one machine

## Out of scope for this workstream

- per-library release automation
- real device orchestration
- advanced scheduler design
- production publishing credentials and secrets

## Notes

Keep the repo shape simple. New packages should follow a repeatable pattern rather than introducing custom layout per library.

This workstream is considered complete for the current bootstrap phase. New foundation work should reopen only if the repo layout, developer entrypoints, or IDE ergonomics materially change.

## Resolved feedback

- **Three-mode model:** The three modes (CPython host, MicroPython target, CircuitPython target) are correct. Unix-port simulation is a verification layer within modes 2 and 3, not a separate developer posture. The distinction already shows up as separate `run.py` tasks. No fourth mode needed.
- **`scripts/run.py` vs `uv`:** `run.py` is the permanent task runner. `uv` replaces the environment/dependency layer when available (auto-detected), not the task orchestration. See "Tooling direction" above.
- **IDE and editor setup documentation:** Document setup for PyCharm, VS Code, and CLI/text-editor workflows as part of the contributor prerequisites task in next-up.md.
