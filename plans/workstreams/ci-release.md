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
- AI-based code review (GitHub Copilot code review — low priority until community contributions begin)
- single-branch model with tag-based stable releases (Decision 0019)

## Current verified slice

- **Branching model:** `main` is the single branch (Decision 0019 revised). PRs target `main`. Stable releases use tags; experimental releases auto-publish on VERSION bump. `promote.yml` triggers stable releases for named libraries.
- **CI (`.github/workflows/ci.yml`):** triggers on push to `main` and on all PRs. Jobs: `lint`, `test` (3.11/3.12/3.13 matrix), `verify-examples`, `build` (with artifact upload), plus PR-only: `version-check`, `api-check`, `label-check`. Advisory MicroPython and CircuitPython compat jobs.
- **Version enforcement:** `scripts/check_version.py` fails PRs that change library `src/` or `pyproject.toml` without a VERSION bump (Decision 0002).
- **API breakage detection:** `scripts/check_api.py` uses `griffe check` to compare current API against last release tag. Cross-references bump level with detected breakages — patch bump with breakages fails; minor bump suffices for 0.x libraries (Decision 0020).
- **Label check:** `label-check` job requires a `semver:*` label on every PR.
- **Release (`.github/workflows/release.yml`):** triggers on VERSION changes pushed to `main` (experimental auto-release). Also accepts `workflow_dispatch` with `channel` (experimental/stable), `libraries`, and `dry_run` inputs. Detects changed libraries, builds distributions, publishes to PyPI via trusted publishing (OIDC, environment "pypi"), creates per-library git tags (with `-experimental` suffix for experimental channel), and creates GitHub Releases (marked pre-release for experimental). Both channels publish to their respective bundle repos.
- **Docs deployment (`.github/workflows/docs-deploy.yml`):** triggers on push to `main` (experimental docs) and via `workflow_dispatch` with `channel=stable` (stable docs, called by `promote.yml`). Deploys per-library docs to GitHub Pages via mike with `--deploy-prefix <lib>`. Also generates and deploys the root landing page.
- **PR template:** `.github/PULL_REQUEST_TEMPLATE.md` with checklist (description, VERSION, labels, preflight, docstrings, docs/examples, no secrets).
- **Labels:** `.github/labels.yml` defines type, library, semver, and process labels. Synced via `label-sync.yml` workflow.
- **AI review:** Will use GitHub Copilot code review once community contributions begin. Low priority until then.
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

- opening a PR to `develop` runs expected checks
- lint and coverage gates fail fast when standards are not met
- merge to `main` can trigger release preparation for the affected library
- release version intent comes from the changed library's checked-in `VERSION` file
- the timing library can prove the end-to-end PR to release flow before the repo scales to more libraries

## Notes

The repo has four publishable libraries: `compat/`, `msgpack/`, `runner/`, and `timing/`. All build and pass preflight. Release automation is in place for tagging and GitHub Releases. PyPI trusted publishing is configured (environment "pypi"); all four libraries have been published to PyPI (currently at 0.1.8). The branching model (Decision 0019 revised — single branch with tags) and API breakage detection (Decision 0020) are defined and wired into CI. `main` is the default (and only) branch. Branch protection rulesets are configured but not enforced until repos go public. `BUNDLE_TOKEN` secret is added. Stable releases are tag-based, triggered by `promote.yml`; experimental releases auto-publish on VERSION bump. Both channels push to their respective bundle repos (`ChuMicro-Bundle` / `ChuMicro-Bundle-Experimental`, Decision 0018). Both repos use the same directory names (no `_experimental` suffix) — channel separation is handled by the repo itself. `scripts/bundle.py` stages .py + .mpy + `package.json`; the `--experimental` flag points `package.json` URLs to the experimental repo. `scripts/bundle.py readme` auto-generates rich README.md files (library table, install commands, source links) from workspace metadata; `release.yml` regenerates them on each bundle push so they stay current without manual updates. The `release.yml` bundle job produces circup-compatible zips with correct naming derived from the repo name (`{bundle_id}-{platform}-{tag}.zip`) and internal structure (`{basename}/lib/`). Only CP 10.x mpy bytecode is produced. Bundle repo policy: no examples, no per-library READMEs, no workflows — all automation lives in the source repo. Remaining items: enforce branch protection once repos are public, validate circup/mip end-to-end install paths once bundle repos are public.

## Resolved feedback

- **Required checks for first protected-branch setup:** Tier 1 (lint, CPython tests, coverage gate, package build). Already reflected in the proposed pipeline tiers above and in CI.
- **Hardware workflows blocking merges:** Manual/scheduled only at first. Already decided (Decision 0003, roadmap.md).
- **CircuitPython artifact staging:** Stage CircuitPython artifacts from the start — the circup repo in the ChuMicro org is the distribution channel. Include both `.py` source and `.mpy` compiled bytecode. Do not wait for PyPI to go first; all three distribution targets (PyPI, circup, mip) should be part of the same release pipeline.
