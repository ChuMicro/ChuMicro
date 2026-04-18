# Next Up

## Now

(empty — pick from Next)

## Next

- [ ] Device testing Phase 3: IDE integration (pytest conftest routes `functional_tests/` to device when `CHUMICRO_DEVICE_RUNTIME` is set) — Decision 0027
- [ ] Enable GitHub Copilot code review as a PR quality gate (low priority — defer until community contributions begin).
- [ ] Implement `chumicro-settings` — dict-like persistent storage for microcontrollers.
  - Uses `chumicro-msgpack` for serialization (2-byte length prefix + msgpack payload).
  - `Settings(backend, *, defaults=None)` with dict-like API (`__getitem__`, `__setitem__`, `get`, `__contains__`, `__len__`, `__iter__`).
  - Explicit `load()` / `save()` — no implicit auto-save (flash wear). `is_dirty` property tracks unsaved changes.
  - Injectable backend protocol (duck-typed): `NvmBackend(nvm)` for CircuitPython, `FileBackend(path)` for MicroPython/CPython, `MemoryBackend(size)` for tests.
  - `testing.py` submodule with `FakeBackend` (wraps MemoryBackend + call recording).
  - Corruption recovery: `load()` catches decode failures, resets to defaults, sets dirty.
  - ESP32 NVS backend deferred (different semantics — per-key, not blob).
- [ ] Add digital I/O as the second library seam (alongside CI/release work, not sequentially).
- [ ] Explore test ergonomics: reduce repeated boilerplate across test files.
- [ ] Validate VS Code workspace end-to-end (configs are generated and structurally correct — needs a live VS Code session to confirm test discovery and import resolution work interactively).
- [ ] Design a performance and resource benchmarking infrastructure. Goals:
  - Measure memory footprint (heap allocations, peak usage) and CPU cost of library operations.
  - Control GC explicitly during benchmarks so allocation measurements are stable and reproducible across runs.
  - Define per-benchmark thresholds that fail the run if exceeded, catching regressions over time.
  - Benchmarks may be slow; they should not run as part of the standard `test` path. Consider a separate `bench` task or a deeper test tier that can also run in CI on a schedule.

## Blocked / waiting

- [ ] Expand the device test matrix beyond ESP32-S2 once transport tooling is proven.
- [ ] Device testing Phase 4: CI integration (`device-test.yml` with `workflow_dispatch`) — blocked on Phase 2 proving reliable on real hardware.

## Done (recent)

- [x] Device testing Phase 2: CircuitPython serial transport — `CircuitpythonTransport` (pyserial raw REPL: Ctrl-C interrupt, Ctrl-A enter, Ctrl-D execute, OK/stdout/stderr parsing), `build_circuitpython_bootstrap` (class-as-module injection, inline harness, test exec), orchestrator routing for CP devices. `pyserial` added to dev deps.
- [x] Device testing infrastructure — Phase 1 complete (Decision 0027): `device_config.py` config loader, `result_parser.py` structured output parsing, `support/device_transport/` with `MicropythonTransport` (mount + copy modes), `name_filter` on `runner.run_module`, real `test-device` orchestration in `run.py` with `--runtime`/`--device`/`--library`/`--test` flags, `mpremote` + `pyyaml` in requirements-dev.txt. 49 new host-side tests.
- [x] Populate "What's new" sections in library guides — all four libraries now have version entries.
- [x] CI build and cache optimizations: `--no-isolation` build (~7x faster), MicroPython submodule pruning (87% cache size reduction), explicit pip caching for docs deploy.
- [x] Documentation sync: run.py commands synced across README, AGENTS.md, and development-cli.md.
- [x] Validate-mpy CI job for PRs: builds mpy-cross, stages all libraries, validates mip install + import from staged bundle. Catches broken mpy compilation or manifest errors before merge.
- [x] Pre-publish bundle validation: `--staging-dir` mode validates mip install against locally staged bundles before pushing to live repos. Integrated as a gate in both `release.yml` and `promote.yml`.
- [x] Mip install validation in CI: `validate-mip` job in `release.yml` and `promote.yml` tests mip install + import for both `.py` and `.mpy6` formats after every bundle push. `validate-mip` run.py subcommand for local use.
- [x] Mpy folder restructuring (Decision 0024): `.mpy` bytecode moved out of root package dirs into `mpy6/` (MicroPython) and `circuitpython-10.x-mpy/` (CircuitPython). Root `package.json` lists `.py` source for universal compatibility; `mpy6/` manifests for users who want pre-compiled bytecode.
- [x] Mip dependency routing: experimental `package.json` references experimental bundle repo for deps (was hardcoded to stable). Fixed "latest" → "HEAD" for git ref resolution.
- [x] CI mpy-cross integration: `release.yml` and `promote.yml` build both mpy-cross compilers from source (cached) instead of `pip install mpy-cross`. Both CircuitPython and MicroPython `.mpy` files are now compiled during bundle staging. New `prepare-mpy-cross` command builds only the compilers without the full unix-port interpreters.
- [x] Promote workflow fixes: inlined stable docs deployment (concurrency group was silently canceling deploys), added attestations to stable PyPI publish, fixed garbled bundle release description.
- [x] CI micropython cache sharing: `validate-mpy`, `runtime-compatibility`, `release.yml`, and `promote.yml` all share the same micropython cache key.
- [x] Docs branding overhaul: warm palette matching badger logo, favicon regeneration, landing page reads descriptions from pyproject.toml, centered logo header in root README, plain-language library descriptions.
- [x] Library README overhaul: absolute URLs for PyPI compatibility, badger tip images, Source links to library directories, README.md included in bundle staging, scaffold template aligned.
- [x] Brand normalization: "Chumicro" → "ChuMicro" across 50+ occurrences in prose, docstrings, templates, and docs.
- [x] Contributor fork workflow: complete fork-to-PR walkthrough in CONTRIBUTING.md, fork sync/rebase guidance, GitHub UI steering for PRs.
- [x] Contributor experience audit v4: "First contribution?" signpost, Contributor FAQ, "abbreviations we spell out" reframing, memory-pattern reassurance repositioning, "Part of ChuMicro" discovery line in all library READMEs, AGENTS.md working-style consolidation.
- [x] Test harness heap deltas: per-test allocation tracking with manual GC control.
- [x] Plans cleanup: removed plans/sessions/, commit history is the primary context recovery mechanism.
- [x] Scripts test suite: 203 pytest tests for scripts/ infrastructure, `test-scripts` subcommand integrated into preflight.
- [x] IDE audit: scripts/ added to source roots, test discovery, and extraPaths in PyCharm and VS Code configs. Stale .iml entries cleaned up. `scripts/tests` added to pytest testpaths.
- [x] Contributor experience audit v3: root README "Your first program" example and REPL snippet, circup bundle explanation, install section cleanup (details blocks for experimental/channel switching in all library READMEs), common-mistakes FAQ in CONTRIBUTING.md, FakeTicks.ticks_add overflow validation, self-contained testing.py constants (fixes CircuitPython compat import skip), architecture guide, editable-install clarification in Other Editors guide.
- [x] Enable GitHub Discussions (Q&A, Ideas, Show and Tell categories).
- [x] Contributor experience audit v2: README reorder (Installation before Development setup), dependency graph, cross-library references (timing ↔ runner), "What's new" sections in all library guides, PR template simplification (N/A defaults), coverage hint in `run.py`, `CLAUDE.md` and `.cursorrules` pointers, GitHub Discussions link in CONTRIBUTING.md and issue template config.
