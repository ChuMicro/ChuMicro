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

- `.github/workflows/ci.yml` runs on `push` to `main` and on `pull_request`
- CI jobs are split: `lint`, `test` (matrix 3.11/3.12/3.13), `verify-examples`, `build`, `version-check` (PR only), plus advisory MicroPython and CircuitPython compat
- `version-check` job uses `scripts/check_version.py` to enforce per-library VERSION bumps when `src/` or `pyproject.toml` changes (Decision 0002)
- `build` job uploads artifacts via `actions/upload-artifact@v4`
- `.github/workflows/release.yml` triggers on VERSION changes pushed to `main`
- release workflow detects changed libraries, builds distributions, publishes to PyPI via trusted publishers (OIDC), creates per-library git tags (`<name>-v<version>`), and creates GitHub Releases
- `scripts/check_version.py` is also available as `python scripts/run.py check-version` for local use
- four publishable libraries (`compat/`, `msgpack/`, `runner/`, `timing/`) are the current proof targets under `libraries/`

## Proposed pipeline tiers

### Tier 1: required on every PR

- lint
- CPython `pytest` unit tests
- coverage gate
- package build verification

### Tier 2: preferred when practical

- MicroPython cross-runtime unit tests
- CircuitPython cross-runtime unit tests
- stub or mock validation for IDE-facing packages

These should start as non-blocking if they are not yet stable enough.

### Tier 3: targeted hardware validation

- `functional_tests/` execution against configured boards
- manual or scheduled workflows
- artifact capture for logs and results

## Release direction

- releases are per library, not per repo
- release intent comes from the affected library's `VERSION` file
- versioning should update the affected package only
- release automation builds standard Python artifacts (PyPI) and board-friendly distribution artifacts

### Distribution targets

- **PyPI:** standard `sdist` and `wheel` publishing. Normal Python packaging — fewest barriers.
- **CircuitPython (circup):** the ChuMicro GitHub org will host a circup-compatible repository. Artifacts should include both `.py` source and `.mpy` compiled bytecode (or offer both as options). `mpy-cross` compilation is part of the release pipeline.
- **MicroPython (mip):** target the same distribution model as CircuitPython where possible. Exact mip staging details to be confirmed once the CircuitPython path is proven.

Platform targeting (Decision 0011) gates which distribution targets receive artifacts for each library.

## Testing stance

`pytest` should stay the primary CI framework for host-based tests.

It should be supplemented with:

- compatibility runners for target runtimes
- a Chumicro on-device harness for `functional_tests/`

It should not be forced to be the direct execution environment on constrained boards unless a later proof shows that is realistic and maintainable.

## Success criteria

- opening a PR to `main` runs expected checks
- lint and coverage gates fail fast when standards are not met
- merge to `main` can trigger release preparation for the affected library
- release version intent comes from the changed library's checked-in `VERSION` file
- the timing library can prove the end-to-end PR to release flow before the repo scales to more libraries

## Notes

The repo has four publishable libraries: `compat/`, `msgpack/`, `runner/`, and `timing/`. All build and pass preflight. Release automation (`.github/workflows/release.yml`) is in place with per-library detection, PyPI publishing via trusted publishers, git tagging, and GitHub Releases. Remaining items: configure the `pypi` GitHub environment and trusted publishers on pypi.org, set up branch protection rules, wire in circup/mip bundle staging (Decision 0018).

## Resolved feedback

- **Required checks for first protected-branch setup:** Tier 1 (lint, CPython tests, coverage gate, package build). Already reflected in the proposed pipeline tiers above and in CI.
- **Hardware workflows blocking merges:** Manual/scheduled only at first. Already decided (Decision 0003, roadmap.md).
- **CircuitPython artifact staging:** Stage CircuitPython artifacts from the start — the circup repo in the ChuMicro org is the distribution channel. Include both `.py` source and `.mpy` compiled bytecode. Do not wait for PyPI to go first; all three distribution targets (PyPI, circup, mip) should be part of the same release pipeline.

