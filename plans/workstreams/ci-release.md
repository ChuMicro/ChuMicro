# Workstream: CI and Release

Status: `in-progress`

## Purpose

Establish predictable PR checks and per-library release automation for a mono-workspace that publishes libraries individually.

## Scope

- GitHub Actions for lint, tests, and coverage
- branch protection expectations
- per-library `VERSION` file enforcement
- per-library build and release steps
- staging targets for PyPI and CircuitPython distribution
- package-aware workflows in a mono-workspace

## Current verified slice

- `.github/workflows/ci.yml` exists and runs on `push` to `main` and on `pull_request`
- CI currently runs required host checks for lint, host-side tests with coverage, and timing package build
- CI now also runs advisory MicroPython and CircuitPython compatibility smoke jobs via `scripts/run.py`
- CI now uses the shared repo task interface in `scripts/run.py`
- the timing package is the current single-package proof target under `libraries/` for CI behavior

## Proposed pipeline tiers

### Tier 1: required on every PR

- lint
- CPython `pytest` unit tests
- coverage gate
- package build verification

### Tier 2: preferred when practical

- MicroPython compatibility smoke tests
- CircuitPython compatibility smoke tests
- stub or mock validation for IDE-facing packages

These should start as non-blocking if they are not yet stable enough.

### Tier 3: targeted hardware validation

- `device_tests/` execution against configured boards
- manual or scheduled workflows
- artifact capture for logs and results

## Release direction

- releases are per library, not per repo
- release intent comes from the affected library's `VERSION` file
- versioning should update the affected package only
- release automation should eventually build both standard Python artifacts and board-friendly distribution artifacts

## Testing stance

`pytest` should stay the primary CI framework for host-based tests.

It should be supplemented with:

- compatibility runners for target runtimes
- a Chumicro on-device harness for `device_tests/`

It should not be forced to be the direct execution environment on constrained boards unless a later proof shows that is realistic and maintainable.

## Success criteria

- opening a PR to `main` runs expected checks
- lint and coverage gates fail fast when standards are not met
- merge to `main` can trigger release preparation for the affected library
- release version intent comes from the changed library's checked-in `VERSION` file
- the timing library can prove the end-to-end PR to release flow before the repo scales to more libraries

## Notes

The repo has already started with checks for a single package: `timing/`.

Release automation is still intentionally incomplete. This workstream remains active until per-library `VERSION` file enforcement, package-aware release selection, and staged publishing are implemented.

## Resolved feedback

- **Required checks for first protected-branch setup:** Tier 1 (lint, CPython tests, coverage gate, package build). Already reflected in the proposed pipeline tiers above and in CI.
- **Hardware workflows blocking merges:** Manual/scheduled only at first. Already decided (Decision 0003, roadmap.md).

## Open decisions

- Should release automation stage CircuitPython artifacts immediately, or only after the timing package proves the basic PyPI build flow?

