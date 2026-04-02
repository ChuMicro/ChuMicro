# Next Up

## Now

- [ ] Generalize the compatibility smoke runner (`ci/run_sample_device_smoke.py`) to discover and exercise device tests for any library, not just timing.
- [ ] Draft the first release workflow for per-library `VERSION` file enforcement and per-library artifacts (PyPI, circup, mip).
- [ ] Document contributor prerequisites by platform (macOS, Linux, Windows/WSL2) and by editor (PyCharm, VS Code, CLI) in the README. Linux and WSL2 sections are best-effort/researched until verified.
  - When writing these docs, scope the AGENTS.md performance guidelines (f-strings, `const()`, `memoryview`, pre-allocated buffers, etc.) to **library code only**. Infrastructure code (`scripts/`, `ci/`, `support/`) runs exclusively on CPython and does not need embedded-runtime constraints.

## Next

- [ ] Scope AGENTS.md performance guidelines (f-strings, `const()`, `memoryview`, pre-allocated buffers) to library code only. Infrastructure code (`scripts/`, `ci/`, `support/`) runs exclusively on CPython and should not be constrained by embedded-runtime rules.
- [ ] Add `[tool.chumicro].platforms` reader to `scripts/run.py` and wire it into the compatibility smoke runners and release/build paths (Decision 0011).
- [ ] Promote advisory MicroPython and CircuitPython CI jobs to protected-branch requirements, gated by platform targeting (Decision 0011).
- [ ] Add digital I/O as the second library seam (alongside CI/release work, not sequentially).
- [ ] Set up ReadTheDocs configuration and initial docs structure for the timing library (`libraries/timing/docs/`).
- [ ] Add usage examples for the timing library (`libraries/timing/examples/`).
- [ ] Explore test ergonomics: reduce repeated boilerplate across test files.
- [ ] Validate VS Code workspace with the generated `pyrightconfig.json`.
- [ ] Add `mpy-cross` compilation step to the release pipeline for circup and mip artifacts.
- [ ] Decide whether to add a second, runtime-specific import smoke layer on top of the canonical shared runner from [Decision 0006](./decisions/0006-shared-import-free-compatibility-smoke-runner.md).
- [ ] Add the first real board transport tooling for ESP32-S2 (Wemos S2-Mini) once the manual device execution path needs to move beyond direct local runs.
- [ ] Refactor `ci/prepare_*.py` to expose importable `main()` functions so `scripts/run.py` can call them directly instead of via subprocess. Keep subprocess only for external tools (`ruff`, `pytest`, `build`, `make`, `micropython`).

## Blocked / waiting

- [ ] Confirm exact mip staging details once the CircuitPython circup path is proven.
- [ ] Expand the device test matrix beyond ESP32-S2 once transport tooling is proven.

## Current host-path note

- [x] Accept `native CPython + WSL2 for unix-port validation` as the current Windows host model.
- [x] Unix ports are the standard local simulation path. Docker containers are not needed at this scale. Revisit if CI build times or contributor onboarding friction justify it.

## Done

- [x] Prove IDE-facing stub packaging with the timing library. Using upstream `circuitpython-stubs` + `micropython-esp32-stubs` (Decision 0012).
- [x] Consolidate runtime version pins into `runtime-versions.toml`. CI prepare scripts, setup, and stubs all read from this single file.
- [x] Establish shared cross-library test fakes via `testing` submodules (e.g., `chumicro_timing.testing.FakeTicks`). Decision 0010.
- [x] Close stale "Feedback requested" sections in workstreams that have been answered by subsequent decisions.
- [x] Decide CircuitPython artifact staging: stage from the start via ChuMicro org circup repo, include `.py` and `.mpy`.
- [x] Decide hardware workflow promotion: promote once board transport tooling has proven reliable.
- [x] Decide first-class test board: ESP32-S2 (Wemos S2-Mini). Matrix expands later.
- [x] Decide second seam: digital I/O, in parallel with CI/release hardening.
- [x] Decide IDE stubs: prove now with the timing library.
- [x] Decide runtime compat CI: promote to mandatory, gated by platform targeting (Decision 0011).
- [x] Decide platform targeting default: no explicit `platforms` key when targeting all three runtimes; document only where useful.
- [x] Decide contributor docs scope: all three OS paths (macOS, Linux, Windows/WSL2); Linux and WSL best-effort until verified.
- [x] Rename `test-host` → `test`. Enforce per-library 90% coverage threshold.
- [x] Auto-discover libraries and support packages in `scripts/run.py` — lint paths, test coverage, source roots, and PYTHONPATH are now derived from the workspace structure instead of hard-coded lists.
- [x] Auto-discover test paths in `pyproject.toml` — `testpaths` and coverage source are now broad patterns; `device_tests/` is excluded via `--ignore-glob`.
- [x] Add root `conftest.py` with auto-discovery of source roots so direct `pytest` invocation works without manual PYTHONPATH.
- [x] Remove unused `_SystemTicks` class from `chumicro_timing.ticks` (dead code — `Heartbeat` uses direct function imports).
- [x] Add scoped `test-host` with `--all`, `--libraries`, branch-diff detection, and pytest passthrough.
- [x] Add `new-library` scaffolder that creates directory structure + regenerates IDE configs.
- [x] Add `sync-ide` task generating `.idea/chumicro.iml` (PyCharm) and `pyrightconfig.json` (VS Code).
- [x] ~~Use `importlib` import mode for pytest~~ — superseded by per-library test runs (Decision 0009).
- [x] Update all prompt files under `plans/prompts/` to reflect current repo state (was stale since pre-rename).
- [x] Choose `workstreams + decisions + next-up + roadmap` as the planning model.
- [x] Save the planning prompt for later refinement.
- [x] Bootstrap the repo with root tooling, planning docs, a runtime support package, and a first CI workflow.
- [x] Keep `venv` as the current workspace path and defer `uv` until later.
- [x] Choose Option B for the sample library, with timing/ticks as the first seam.
- [x] Choose manual-only hardware workflows for the initial phase.
- [x] Implement the first `sample/` package as a timing-first Option B proof.
- [x] Add the first lightweight `support/test_harness/` scaffold for device tests.
- [x] Add repo-level CI coverage for the runtime package, test harness, and sample package.
- [x] Add `plans/prompts/` for saved planning prompts and workspace build-up history.
- [x] Expand `plans/prompts/` with current-state, rebuild, and history prompts.
- [x] Add a restart-time resume prompt under `plans/prompts/`.
- [x] Add shared repo-level task entrypoints for `lint`, `test-host`, `build-sample`, `test-micropython-compat`, `test-circuitpython-compat`, and `test-device`.
- [x] Add the first compatibility runner scaffold for the `sample/` package using `ci/run_sample_device_tests.py`.
- [x] Add `devices.example.yml` and document the first manual device-run workflow.
- [x] Add a repo-managed `prepare-micropython` path that builds a pinned MicroPython unix-port runtime under `.tools/`.
- [x] Exercise the checked-in `test-micropython-compat` path successfully with the prepared local MicroPython unix-port binary.
- [x] Add a single `test-runtime-matrix` entrypoint for the currently proven CPython + MicroPython path.
- [x] Add a repo-managed `prepare-circuitpython` path and replace the CircuitPython placeholder with a real local build-and-run compatibility entrypoint.
- [x] Add advisory CI jobs for `test-micropython-compat` and `test-circuitpython-compat`.
- [x] Choose `ci/run_sample_device_smoke.py` as the canonical shared compatibility smoke runner and keep `ci/run_sample_device_tests.py` as a compatibility wrapper.
- [x] Evaluate CircuitPython `ports/unix/` as a concrete local build/import path without treating it as committed CI scope yet.
- [x] Fix CI compat jobs to actually prepare unix-port binaries before running smoke tests.
- [x] Fix `test-micropython-compat` to auto-prepare like `test-circuitpython-compat`.
- [x] Expand `test-runtime-matrix` to include CircuitPython (CPython + MicroPython + CircuitPython).
- [x] Add `setup` and `preflight` tasks to `ci/tasks.py`.
- [x] Add `VERSION` files for `support/runtime/` and `support/test_harness/`.  *(later removed — support packages are workspace-internal and not published)*
- [x] Consolidate version to single source of truth: `VERSION` file per library under `libraries/`, `pyproject.toml` reads via setuptools `dynamic`, removed hardcoded `__version__` from `chumicro_runtime`.
- [x] Trim README to user-facing content; moved planning prose to `plans/`.

