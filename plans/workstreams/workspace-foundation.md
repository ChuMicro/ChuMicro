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
- `.github/workflows/ci.yml` exists and uses the shared repo task entrypoints
- `scripts/run.py` exists as the current shared task interface for humans, agents, and CI
- `scripts/run.py` auto-discovers all libraries and support packages (no hard-coded lists)
- `scripts/run.py` provides scoped test running: `--all`, `--libraries`, branch-diff detection, pytest passthrough
- `scripts/run.py new-library <name>` scaffolds a new library and regenerates IDE configs
- `scripts/run.py sync-ide` generates `.idea/chumicro.iml` (PyCharm) and `pyrightconfig.json` (VS Code)
- Root `conftest.py` auto-discovers source roots and excludes `device_tests/`
- `pyproject.toml` uses `--import-mode=importlib` for multi-library test isolation
- `ci/prepare_micropython.py` exists as the current repo-managed MicroPython runtime bootstrap path
- `ci/prepare_circuitpython.py` exists as the current repo-managed CircuitPython runtime bootstrap path
- `ci/run_sample_device_smoke.py` exists as the canonical checked-in compatibility smoke entrypoint
- `ci/run_sample_device_tests.py` exists as a backward-compatible wrapper around the canonical smoke runner
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
- import and behavior smoke tests
- selected on-device tests

This mode should avoid direct dependency on CPython-only libraries and should exercise the same public library API whenever possible.

### 3. CircuitPython target mode

Primary use:

- compatibility validation
- import and behavior smoke tests
- selected on-device tests on mounted boards or via a transport tool

This mode should validate the same public API while allowing a small shim for platform-specific modules.

## Platform switching model

Developers should not manually rewrite imports or edit files to switch platforms.

Instead, switching should happen through:

- runtime detection in shared shim code
- dependency injection for hardware-facing pieces
- separate test layers for host logic, compatibility checks, and device execution
- one shared task interface for common actions such as `test-host`, `test-micropython-compat`, `test-circuitpython-compat`, and `test-device`

Current verified implementation:

- the shared task interface lives in `scripts/run.py`
- CI uses the same task interface for lint, host tests, timing package build, and advisory runtime compatibility jobs
- compatibility and device commands exist now as honest scaffolding entrypoints rather than hidden future intent

## Tooling direction

Current verified state:

- standard virtual environment
- `pytest`
- `pytest-cov`
- `ruff`
- `scripts/run.py` as the current repo-level command surface

Proposed direction:

- use `uv` as the preferred repo-level tool runner once per-package dependency groups are defined
- keep plain `venv` as a documented fallback so contributors are not blocked

Current decision:

- keep `venv` as the active documented path for now
- reconsider `uv` only after the current `scripts/run.py` interface needs stronger environment or task management

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

## Feedback requested

- Is the three-mode model correct, or do you want a fourth explicit mode for simulation/emulation?
- Should `scripts/run.py` remain the long-term human/agent entrypoint, or do you want it treated as a temporary bridge until `uv` is adopted?
- Do you want PyCharm-specific setup steps documented next, or is the current predictable `src/` layout sufficient for now?

