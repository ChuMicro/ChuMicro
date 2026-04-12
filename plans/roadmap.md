# Roadmap

The workspace is designed to grow to 40–50+ libraries.  Tooling, CI, docs, and discovery patterns should be evaluated against that scale, not just the current library count.

## Milestone 0 — workspace bootstrap

Status: `done`

Goal: establish the mono-workspace shape, shared tooling, initial plans, and one tiny reusable support package.

Settled choices: `venv`/`pip` as fallback with `uv` auto-detected; `scripts/` for developer tasks; `plans/` for planning docs.

## Milestone 1 — timing library proof

Status: `done`

Goal: add a `timing` library that proves packaging, testing, and cross-runtime structure.

Settled choices: Option B (logic + hardware-facing seam); timing/ticks as first seam; digital I/O deferred as second seam; IDE stubs from upstream PyPI packages; MkDocs + Material + mkdocstrings for docs.

Additional libraries built during Milestone 1: `runner` (Decision 0014), `compat` (`functools.partial` polyfill), `msgpack` (cross-runtime MessagePack with native C delegation).

## Milestone 2 — CI and release flow

Status: `done`

Goal: prove branch → PR → checks → merge → release staging.

Settled choices: single-branch model with tag-based stable releases (Decision 0019); required PR checks include lint, tests, coverage, build, MP/CP compat, version-check, api-check, validate-mpy; all three distribution targets (PyPI, circup, mip) in the same release pipeline; per-repo SSH deploy keys for bundle repos; mpy-cross compiled from source (both runtimes) during bundle staging (Decision 0024); pre-publish mip validation via `--staging-dir` before pushing to live bundle repos; post-publish mip validation as CDN smoke test.

## Milestone 3 — device validation and simulation

Status: `proposed`

Goal: add simulation-first device validation and optional home testbed execution.

Exit criteria:

- device registry template exists
- simulation/emulation path is part of CI where practical
- hardware workflow can target user-managed boards when configured
- functional test harness contract is defined and exercised

Key choices to confirm:

- whether MicroPython Unix port is sufficient as an early compatibility signal
- whether CircuitPython should rely on mocks first, or whether you want a board-run path in the first implementation wave
- how much of the home testbed should block PRs versus run on demand

Current answer:

- hardware workflows should be manual only at first; promote once board transport tooling has proven reliable
- MicroPython should use CPython + Unix-port validation + later real-board runs
- CircuitPython should use the same ladder if the unix port is practical; otherwise start with mocks and then real boards
- Windows should use native CPython for general development and WSL2 for unix-port-based validation
- first-class test target: ESP32-S2 (Wemos S2-Mini); matrix will expand later
- CI-hosted hardware is a future goal but high-security; users configure local test matrices via `devices.yml`

## Settled questions

- MicroPython and CircuitPython CI compatibility checks are now required status checks on PRs, gated by platform targeting (Decision 0011).
- Hardware workflows stay manual-only until board transport tooling exists and has proven reliable.
- Release automation stages artifacts for all three targets (PyPI, circup, mip) from the start — do not wait for PyPI to go first.
