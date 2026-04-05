# Next Up

## Now

- [ ] Create `develop` branch on GitHub, set as default branch, configure branch protection on both `develop` and `main` (Decision 0019).
- [ ] Integrate AI review tool (TBD — custom solution to be provided).
- [ ] Document contributor prerequisites by platform (macOS, Linux, Windows/WSL2) and by editor (PyCharm, VS Code, CLI) in the README. Linux and WSL2 sections are best-effort/researched until verified.
  - When writing these docs, scope the AGENTS.md performance guidelines (f-strings, `const()`, `memoryview`, pre-allocated buffers, etc.) to **library code only**. Infrastructure code (`scripts/`, `support/`) runs exclusively on CPython and does not need embedded-runtime constraints.
- [ ] Write a "Creating a New Library" contributor guide. Walk through the full lifecycle from scaffolding to release-ready:
  1. `new-library` scaffolding — what it creates, what it doesn't (e.g., no `testing` submodule by default)
 2. Library code — dependency injection (Decision 0010), `check(now_ms) -> bool` gate-based contract for active components (Decision 0014), memory-efficient patterns for embedded targets
  3. Unit tests — per-library test runs (Decision 0009), 90% coverage threshold, constructor injection for testability
  4. Testing submodule — when and how to add `src/chumicro_<name>/testing.py` with ready-made fakes
  5. Docs — `guide.md` required sections, `api.md` autodoc rules, generation prompt (Decision 0013)
  6. Examples — top-level style (no `__main__` guard), verified via AST-based import checking in preflight (Decision 0013)
  7. VERSION bumps — semantic versioning rules, when to bump
  8. Preflight — running `python scripts/run.py preflight` before committing
  - This should live in the repo (e.g., `docs/creating-a-library.md` or a top-level `CONTRIBUTING.md` section), not just in AGENTS.md or decision records.

## Next
- [ ] Implement `chumicro-settings` — dict-like persistent storage for microcontrollers.
  - Uses `chumicro-msgpack` for serialization (2-byte length prefix + msgpack payload).
  - `Settings(backend, *, defaults=None)` with dict-like API (`__getitem__`, `__setitem__`, `get`, `__contains__`, `__len__`, `__iter__`).
  - Explicit `load()` / `save()` — no implicit auto-save (flash wear). `is_dirty` property tracks unsaved changes.
  - Injectable backend protocol (duck-typed): `NvmBackend(nvm)` for CircuitPython, `FileBackend(path)` for MicroPython/CPython, `MemoryBackend(size)` for tests.
  - `testing.py` submodule with `FakeBackend` (wraps MemoryBackend + call recording).
  - Corruption recovery: `load()` catches decode failures, resets to defaults, sets dirty.
  - ESP32 NVS backend deferred (different semantics — per-key, not blob).
- [ ] Add `[tool.chumicro].platforms` reader to `scripts/run.py` and wire it into the cross-runtime compatibility runners and release/build paths (Decision 0011).
- [ ] Promote advisory MicroPython and CircuitPython CI jobs to protected-branch requirements, gated by platform targeting (Decision 0011).
- [ ] Add digital I/O as the second library seam (alongside CI/release work, not sequentially).
- [ ] Set up ReadTheDocs hosting with `.readthedocs.yaml` and wire docs build into CI/release pipeline (Decision 0013).
- [ ] Add docs build verification to the release pipeline (verify `docs/` is non-empty for any library being released).
- [ ] Explore test ergonomics: reduce repeated boilerplate across test files.
- [ ] Validate VS Code workspace with the generated `pyrightconfig.json`.
- [ ] Add `mpy-cross` compilation step to the release pipeline for circup and mip artifacts.
- [ ] Add the first real board transport tooling for ESP32-S2 (Wemos S2-Mini) once the manual device execution path needs to move beyond direct local runs.
- [ ] Design a performance and resource benchmarking infrastructure. Goals:
  - Measure memory footprint (heap allocations, peak usage) and CPU cost of library operations.
  - Control GC explicitly during benchmarks so allocation measurements are stable and reproducible across runs.
  - Define per-benchmark thresholds that fail the run if exceeded, catching regressions over time.
  - Benchmarks may be slow; they should not run as part of the standard `test` path. Consider a separate `bench` task or a deeper test tier that can also run in CI on a schedule.
  - Evaluate whether MicroPython's `micropython.mem_info()` and `gc.mem_alloc()`/`gc.mem_free()` can provide the data, and what CPython equivalents (`tracemalloc`, `resource`) to use for host-side benchmarks.
  - Keep the benchmark harness cross-runtime where possible, with runtime-specific measurement backends.

## Blocked / waiting

- [ ] Confirm exact mip staging details once the CircuitPython circup path is proven.
- [ ] Expand the device test matrix beyond ESP32-S2 once transport tooling is proven.

## Done

- [x] Establish develop → main branching model (Decision 0019), API breakage detection with griffe (Decision 0020), PR quality gates (template, labels, semver label check), promote workflow, label sync workflow. CI split into lint/test/build/verify-examples/version-check/api-check/label-check jobs. Release workflow creates tags and GitHub Releases (PyPI publishing scaffolded but disabled).
- [x] Draft first release workflow: `release.yml` triggers on VERSION changes pushed to main, detects changed libraries, builds, publishes to PyPI via trusted publishers (OIDC), creates git tags and GitHub Releases. `ci.yml` split into lint/test/build/verify-examples/version-check jobs. `scripts/check_version.py` enforces per-library VERSION bumps for release-relevant changes (Decision 0002).
- [x] Add `chumicro-msgpack` library: pure-Python MessagePack encoder/decoder with native CircuitPython C delegation.  Bytes API (`packb`/`unpackb`) and stream API (`pack`/`unpack`).  Docs, examples (including CircuitPython NVM hardware example), struct-vs-msgpack guidance.
- [x] Add `functools.partial` polyfill to `chumicro-compat`: `_PurePythonPartial` for MicroPython/CircuitPython, re-exports real `functools.partial` on CPython.  12 tests, docs, examples.
- [x] Fix cross-runtime test harness: `time.monotonic` shim for MicroPython, replace `pytest.raises` with `chumicro_test_harness.raises` in msgpack tests.
- [x] Implement and iterate `chumicro-runner` to gate-based pattern (Decision 0014).  Service contract: `check(now_ms) -> bool`.  `Runner` with `add()`, `add_periodic()`, `TaskHandle`, shared timestamps, batch firing.  `CallRecorder` test helper.  All library versions reset to 0.1.0.
- [x] Add `chumicro-compat` library (initially with `abc` module, later replaced by `functools.partial` polyfill).
- [x] Generalize the compatibility smoke runner to discover and exercise device tests for any library, not just timing.
- [x] Scope AGENTS.md performance guidelines (f-strings, `const()`, `memoryview`, pre-allocated buffers) to library code only. Infrastructure code (`scripts/`, `support/`) runs exclusively on CPython and should not be constrained by embedded-runtime rules.
- [x] Move prepare logic from `ci/prepare_*.py` into importable modules under `scripts/`. `ci/` was subsequently removed entirely — all logic now lives in `scripts/`.
- [x] Review `scripts/run.py` layering. Split into focused modules: `discovery.py`, `ide.py`, `scaffold.py`, `prepare.py`, `prepare_micropython.py`, `prepare_circuitpython.py`, `prepare_workspace.py`. `run.py` is now a slim dispatch-and-task file. `dev_packages` moved to `requirements-dev.txt`.
- [x] Accept `native CPython + WSL2 for unix-port validation` as the current Windows host model.
- [x] Unix ports are the standard local simulation path. Docker containers are not needed at this scale. Revisit if CI build times or contributor onboarding friction justify it.
- [x] Audit the `chumicro-runner` library implementation (Decision 0014). Review API surface, allocation patterns, and integration with Heartbeat.
- [x] Drop hand-written member lists from `api.md` files; codify `api.md` rules in Decision 0013 (no hand-written signatures, module-level `:::` directives only, fix docstrings not api.md).
- [x] Add strict `guide.md` required-section structure and AI generation prompt (`plans/prompts/guide-generation.prompt.md`). Decision 0013 updated with required-section table and generation rules.
- [x] Implement the runner pattern as `chumicro-runner` library (Decision 0014).
- [x] Wire up MkDocs + Material + mkdocstrings: per-library `mkdocs.yml`, `docs` task in `scripts/run.py`, `api.md` converted to autodoc directives (Decision 0013).
- [x] Add per-library scoping (`--all`/`--libraries`) to `verify-examples` and `docs` tasks (shared `_parse_scope_args` helper).
- [x] Update `new-library` scaffolder: generates `mkdocs.yml`, `docs/api.md` with autodoc, `docs/guide.md` template, and example with `__main__` guard. No `.gitkeep` in `docs/` or `examples/` — they have real content from scaffolding.
- [x] Add mkdocs dependencies to `setup` task.
- [x] Choose MkDocs + Material + mkdocstrings as the docs build tool. Static analysis (griffe) avoids importing modules with CircuitPython-only deps (Decision 0013).
- [x] Add `verify-examples` task to `scripts/run.py` — import-checks all examples via subprocess. Wired into `preflight` (Decision 0013).
- [x] Add `__main__` guards to all timing library examples so they are importable for verification.
- [x] Add docs and examples for the timing library: user guide, API reference, testing helpers docs, and three runnable examples (Decision 0013).
- [x] Establish docs and examples contributor standards (Decision 0013).
- [x] Add `examples/` to lint discovery paths in `scripts/run.py`.
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
- [x] Auto-discover test paths in `pyproject.toml` — `testpaths` and coverage source are now broad patterns; `functional_tests/` is excluded via `--ignore-glob`.
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
