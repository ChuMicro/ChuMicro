# Workstream: CI and Release

Status: `in-progress`

## Purpose

Establish predictable PR checks and per-library release automation for a mono-workspace that publishes libraries individually.

## Scope

- GitHub Actions for lint, tests, and coverage
- branch protection expectations
- per-library `VERSION` file enforcement
- API breakage detection with griffe
- per-library build and release steps
- staging targets for PyPI and CircuitPython distribution
- package-aware workflows in a mono-workspace
- AI-based code review (tool TBD — will be provided separately)
- develop → main branching model (Decision 0019)

## Current verified slice

- **Branching model:** `develop` is the staging/default branch; `main` is the stable release branch (Decision 0019). PRs target `develop`. `promote.yml` workflow dispatches a develop → main PR for release cuts.
- **CI (`.github/workflows/ci.yml`):** triggers on push to `develop` and `main`, and on all PRs. Jobs: `lint`, `test` (3.11/3.12/3.13 matrix), `verify-examples`, `build` (with artifact upload), plus PR-only: `version-check`, `api-check`, `label-check`. Advisory MicroPython and CircuitPython compat jobs.
- **Version enforcement:** `scripts/check_version.py` fails PRs that change library `src/` or `pyproject.toml` without a VERSION bump (Decision 0002).
- **API breakage detection:** `scripts/check_api.py` uses `griffe check` to compare current API against last release tag. Cross-references bump level with detected breakages — patch bump with breakages fails; minor bump suffices for 0.x libraries (Decision 0020).
- **Label check:** `label-check` job requires a `semver:*` label on every PR.
- **Release (`.github/workflows/release.yml`):** triggers on VERSION changes pushed to `main`, detects changed libraries, builds distributions, creates per-library git tags (`<name>-v<version>`), and creates GitHub Releases. PyPI publishing is scaffolded but disabled until trusted publisher is configured. Supports `workflow_dispatch` with dry-run option.
- **PR template:** `.github/PULL_REQUEST_TEMPLATE.md` with checklist (description, VERSION, labels, preflight, docstrings, docs/examples, no secrets).
- **Labels:** `.github/labels.yml` defines type, library, semver, and process labels. Synced via `label-sync.yml` workflow.
- **AI review:** Tool TBD — will be provided separately. The CI workflow has a placeholder for an AI review required check.
- **Local tasks:** `python scripts/run.py check-version`, `check-api` available for pre-commit verification.
- Four publishable libraries (`compat/`, `msgpack/`, `runner/`, `timing/`) are the current proof targets.

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

The repo has four publishable libraries: `compat/`, `msgpack/`, `runner/`, and `timing/`. All build and pass preflight. Release automation is in place for tagging and GitHub Releases; PyPI publishing is scaffolded but disabled. The branching model (Decision 0019) and API breakage detection (Decision 0020) are defined and wired into CI. Bundle publishing to `ChuMicro/chumicro-bundle` is wired into the release workflow (Decision 0018): `scripts/bundle.py` stages .py + .mpy + `package.json`, the `bundle` job pushes to the bundle repo and creates circup-format release zips. Remaining items: create the `develop` branch on GitHub, set it as default, configure branch protection, integrate the AI review tool (TBD), enable PyPI publishing when ready, create the `chumicro-bundle` repo and add `BUNDLE_TOKEN` secret.

## Resolved feedback

- **Required checks for first protected-branch setup:** Tier 1 (lint, CPython tests, coverage gate, package build). Already reflected in the proposed pipeline tiers above and in CI.
- **Hardware workflows blocking merges:** Manual/scheduled only at first. Already decided (Decision 0003, roadmap.md).
- **CircuitPython artifact staging:** Stage CircuitPython artifacts from the start — the circup repo in the ChuMicro org is the distribution channel. Include both `.py` source and `.mpy` compiled bytecode. Do not wait for PyPI to go first; all three distribution targets (PyPI, circup, mip) should be part of the same release pipeline.
