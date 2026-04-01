# Roadmap

## Milestone 0 — workspace bootstrap

Status: `done`

Goal: establish the mono-workspace shape, shared tooling, initial plans, and one tiny reusable support package.

Exit criteria:

- root repo has a shared `pyproject.toml`
- root repo has CI for lint + tests + coverage
- `plans/` exists with workstreams, decisions, and `next-up.md`
- `support/runtime/` exists with tests passing on CPython

Key choices to confirm:

- keep the current root layout, or add `ci/` now instead of later
- keep plain `venv` as the short-term default, or switch the workspace to `uv` immediately

Current answer:

- keep `venv` for now and revisit `uv` after `sample/` exists or later

Verified notes:

- `plans/prompts/` exists for saved prompts that help rebuild workspace context or preserve workspace build-up history
- `plans/prompts/` now includes prompt files for planning refresh, workspace rebuild, and workspace history capture

## Milestone 1 — sample library proof

Status: `in-progress`

Goal: add a `sample` library that proves packaging, testing, and cross-runtime structure.

Exit criteria:

- `sample/` has `src/`, `tests/`, `device_tests/`, and `doc/`
- host tests pass with 90%+ coverage
- sample package can build as an individual distribution
- IDE-friendly stubs or mocks exist for developer ergonomics

The sample library should prove all of these:

- one public API shared by CPython, MicroPython, and CircuitPython
- platform-specific differences hidden behind a small shim or injected adapter
- host-side `pytest` tests for logic and contract behavior
- on-device tests only for runtime-specific behavior that cannot be trusted from mocks

Key choices to confirm:

- should `sample` be mostly pure logic, or intentionally include one small hardware-facing integration
- should library stubs be generated, hand-written, or deferred until a second package exists

Current answer:

- `sample` should intentionally include one small hardware-facing seam
- the first seam is timing/ticks, with digital I/O likely next

Current verified progress:

- `sample/` exists with `src/`, `tests/`, `device_tests/`, and `doc/`
- host-side tests pass with coverage above the current repo threshold
- the sample package builds as an individual distribution
- shared repo-level task entrypoints exist in `ci/tasks.py`
- a repo-managed MicroPython preparation command exists in `ci/prepare_micropython.py`
- a checked-in shared compatibility smoke runner exists in `ci/run_sample_device_smoke.py`, with `ci/run_sample_device_tests.py` kept as a wrapper
- the MicroPython unix-port smoke test has been exercised successfully in this workspace using the repo-managed local runtime
- a repo-managed CircuitPython preparation command now exists in `ci/prepare_circuitpython.py`
- `ci/tasks.py test-circuitpython-compat` now performs a real local prepare-and-run attempt instead of returning a placeholder result
- the pinned local CircuitPython `10.1.4` unix-port build now completes successfully in this macOS workspace
- the shared timing smoke runner now passes in this workspace under CPython, MicroPython unix-port, and CircuitPython unix-port
- `.github/workflows/ci.yml` now includes advisory MicroPython and CircuitPython compatibility jobs in addition to the required host lane
- `devices.example.yml` exists for the first manual device-validation template
- IDE-facing stub packaging is still open

Still intentionally incomplete:

- promotion of the CircuitPython unix-port path into the default runtime matrix/CI policy is still undecided beyond this verified local macOS workspace
- real board transport tooling is not implemented yet
- release automation is not implemented yet
- per-library `VERSION` file enforcement workflows are not implemented yet
- IDE stub package strategy is not implemented yet
- the second seam after timing/ticks is not implemented yet

Best next implementation slice:

- decide whether the advisory MicroPython unix-port CI lane should stay optional or become part of the default protected-branch policy
- decide whether the advisory CircuitPython unix-port CI lane should stay optional or become part of the default protected-branch policy
- decide whether to add a second runtime-specific import smoke layer on top of the canonical shared runner from Decision 0006
- begin the first release-automation slice around per-library `VERSION` file enforcement once the compatibility entrypoints have one exercised target

## Milestone 2 — CI and release flow

Status: `proposed`

Goal: prove branch → PR → checks → merge → release staging.

Exit criteria:

- PR checks run on GitHub Actions
- coverage gate and lint gate are enforced
- PR checks enforce per-library `VERSION` file updates for release-relevant changes
- sample release artifacts are produced for PyPI and CircuitPython distribution staging

Suggested pipeline shape:

- required PR checks: lint, CPython tests, coverage, package build
- optional or non-blocking checks: MicroPython compatibility smoke tests, CircuitPython compatibility smoke tests
- opt-in or scheduled checks: hardware-backed `device_tests/`

## Milestone 3 — device validation and simulation

Status: `proposed`

Goal: add simulation-first device validation and optional home testbed execution.

Exit criteria:

- device registry template exists
- simulation/emulation path is part of CI where practical
- hardware workflow can target user-managed boards when configured
- on-device test harness contract is defined and exercised

Key choices to confirm:

- whether MicroPython Unix port is sufficient as an early compatibility signal
- whether CircuitPython should rely on mocks first, or whether you want a board-run path in the first implementation wave
- how much of the home testbed should block PRs versus run on demand

Current answer:

- hardware workflows should be manual only at first
- MicroPython should use CPython + Unix-port validation + later real-board runs
- CircuitPython should use the same ladder if the unix port is practical; otherwise start with mocks and then real boards
- Windows should use native CPython for general development and WSL2 for unix-port-based validation

## Feedback requested

- Which milestone feels under-specified?
- Which milestone is trying to do too much?
- Which of the key choices above already has a clear answer in your head?

