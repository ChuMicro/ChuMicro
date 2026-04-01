# Chumicro

Chumicro is a mono-workspace for Python libraries that aim to run across CPython, MicroPython, and CircuitPython.

This repository is being bootstrapped around a few core ideas from `Agents.md`:

- one workspace with many individually published libraries
- shared support packages for runtime detection, mocks, and test tooling
- CPython-first development and testing, with simulation/emulation preferred over hardware when possible
- optional real-device validation for boards registered in a local testbed

## How the three-platform workflow should work

Chumicro should treat the three runtimes as three execution targets for the same library contract:

- **CPython** is the default development target. Most coding, unit tests, linting, coverage, packaging, and IDE work happens here.
- **MicroPython** is a target runtime. It should be validated through compatibility smoke tests, emulation where practical, and selected real-device tests.
- **CircuitPython** is a target runtime. It should be validated through compatibility smoke tests, board-friendly mocks, and selected real-device tests.

The intended developer loop is:

1. write or update code against a small public API and runtime shims
2. run host-side tests on CPython
3. run compatibility checks for MicroPython and CircuitPython paths
4. run on-device tests only for behavior that cannot be trusted from host-only mocks

The repo now provides a small shared task interface so humans and agents do not need to remember different ad hoc commands per runtime.

## Testing model

The current direction is a three-layer test model:

- **required**: CPython-hosted `pytest` tests with coverage
- **preferred when realistic**: simulation or emulation for MicroPython and CircuitPython behavior
- **opt-in / targeted**: real-device `device_tests/` run through a small Chumicro test harness

`pytest` remains the right default for host-based development. It is likely **not** the right tool to run directly on constrained boards, so the current plan is to supplement it rather than replace it.

## Current bootstrap scope

This first implementation slice sets up:

- repo-level Python tooling configuration in `pyproject.toml`
- repo-level task entrypoints in `ci/tasks.py`
- planning documents in `plans/`
- a minimal reusable runtime support package in `support/runtime/`
- a minimal device-test harness in `support/test_harness/`
- a timing-first `sample/` package that proves the first cross-runtime library slice
- a first GitHub Actions CI workflow in `.github/workflows/ci.yml`

The harder pieces are intentionally deferred until the workspace foundation is stable:

- target-runtime compatibility checks beyond CPython-hosted tests
- label-driven release automation and publishing to PyPI / CircuitPython distribution targets
- home testbed integration for hardware validation

## Repository shape

```text
chumicro/
├── ci/
├── devices.example.yml
├── plans/
│   ├── decisions/
│   ├── prompts/
│   └── workstreams/
├── support/
│   ├── runtime/
│   └── test_harness/
├── sample/
└── .github/
    └── workflows/
```

## Local development

### Current verified path

Create or reuse a virtual environment, then install the bootstrap tooling:

```zsh
cd /path/to/chumicro
python -m pip install -U pip
python -m pip install pytest pytest-cov ruff
```

### Proposed default direction

For a multi-package workspace like this one, `uv` is likely the better long-term default because it can manage a repo-level tool environment and package-specific workflows more cleanly than ad hoc virtualenv commands.

That said, the current repository bootstrap has only been verified with a standard virtual environment so far. The repo should not switch its documented default to `uv` until the workspace tasks and per-package dependency model are defined.

### Windows host path (current phase)

Windows is a supported host for general development in the current workspace phase, but unix-port validation should use WSL2 rather than native-Windows unix-port workflows.

- use native Windows for editing, IDE work, linting, host-side tests, and package builds
- use WSL2 for unix-port-based runtime checks such as `python ci/tasks.py test-micropython-compat`
- do not assume native-Windows unix-port builds are part of the supported path in this phase
- `python ci/tasks.py prepare-circuitpython` and `python ci/tasks.py test-circuitpython-compat` now complete successfully in this macOS workspace using the repo-managed local CircuitPython unix-port runtime, but the broader host matrix is still intentionally conservative until other hosts are exercised

Run the current checks:

```zsh
cd /path/to/chumicro
python ci/tasks.py lint
python ci/tasks.py test-host
python ci/tasks.py build-sample
```

Prepare the shared MicroPython runtime and run the current MicroPython smoke test:

```zsh
cd /path/to/chumicro
python ci/tasks.py prepare-micropython
python ci/tasks.py test-micropython-compat
```

Evaluate the shared CircuitPython runtime path:

```zsh
cd /path/to/chumicro
python ci/tasks.py prepare-circuitpython
python ci/tasks.py test-circuitpython-compat
```

This CircuitPython path is still local-first rather than a required CI lane, but in this workspace on macOS the pinned upstream `10.1.4` unix-port build now completes and the shared timing smoke test passes.

Run the currently proven CPython + MicroPython test matrix with one command:

```zsh
cd /path/to/chumicro
python ci/tasks.py test-runtime-matrix
```

## Shared repo-level task entrypoints

The repository now exposes a small, explicit command surface in `ci/tasks.py` so humans, agents, and CI can use the same entrypoints:

- `python ci/tasks.py lint`
- `python ci/tasks.py test-host`
- `python ci/tasks.py build-sample`
- `python ci/tasks.py prepare-micropython`
- `python ci/tasks.py prepare-circuitpython`
- `python ci/tasks.py test-micropython-compat`
- `python ci/tasks.py test-runtime-matrix`
- `python ci/tasks.py test-circuitpython-compat`
- `python ci/tasks.py test-device`

The CPython, package-build, MicroPython, and local CircuitPython entrypoints are now all proven in this workspace. The device task remains a manual transport placeholder.

GitHub Actions keeps lint, host-side tests, coverage, and package build as the required default lane. It now also runs advisory MicroPython and CircuitPython compatibility smoke jobs so target-runtime drift is visible without making those checks required yet.

In this repo, **advisory** means the job still runs on CI and still reports a real pass/fail result, but it is configured not to fail the overall workflow yet. Concretely, the runtime jobs in `.github/workflows/ci.yml` use `continue-on-error: true`, so they surface signal without acting as protected-branch gates.

## How platform switching works right now

The repo switches between runtimes by changing the interpreter used to execute the same library files and test harnesses:

- **CPython**: run `python ci/tasks.py test-host`
- **MicroPython Unix port**: run `python ci/tasks.py prepare-micropython`, then run `python ci/tasks.py test-micropython-compat`
- **CircuitPython Unix port**: run `python ci/tasks.py prepare-circuitpython`, then run `python ci/tasks.py test-circuitpython-compat`

The shared compatibility smoke logic lives in `ci/run_sample_device_smoke.py`, with `ci/run_sample_device_tests.py` kept as a small backward-compatible wrapper. It runs the sample timing smoke test through `support/test_harness/` using the same sample library code under a different interpreter. The repo-local preparation commands build pinned MicroPython and CircuitPython unix-port runtimes under `.tools/` so shared workspaces do not need machine-specific global installs.

For CircuitPython, the current local unix-port preparation path also documents the verified build flags in `ci/prepare_circuitpython.py`. Those flags were added only after reproducing actual local build failures and re-running the build successfully.

## Manual device validation

Real-board execution is still manual-only.

The committed template is `devices.example.yml`. Copy it to `devices.yml`, fill in your board details, and use that as local configuration for future board tooling. The current `test-device` task intentionally does not pretend there is already an automated transport layer.

## Next milestones

- decide the first CircuitPython compatibility-check path beyond host-side `pytest`
- add shared mocks and IDE stub packaging support
- add device registry, simulation/emulation paths, and optional workflow-driven home testbed execution
- add release workflows keyed off per-library `VERSION` files and PR validation for required version edits

## Current open questions

- when should `uv` replace the current `venv`-based documented workflow, if at all
- whether the first exercised target-runtime path should be MicroPython-only at first, or whether CircuitPython compatibility should be pursued in parallel
- when IDE-facing stubs should be introduced relative to the next sample seam

