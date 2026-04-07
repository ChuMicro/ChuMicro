# Next Up

## Now

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
- [ ] Validate VS Code workspace end-to-end (generated `pyrightconfig.json`, `settings.json`, `tasks.json` — not yet tested in a live VS Code session).
- [ ] Validate circup/mip install paths end-to-end once bundle repos are public (Decision 0018).
- [ ] Add the first real board transport tooling for ESP32-S2 (Wemos S2-Mini) once the manual device execution path needs to move beyond direct local runs.
- [ ] Design a performance and resource benchmarking infrastructure. Goals:
  - Measure memory footprint (heap allocations, peak usage) and CPU cost of library operations.
  - Control GC explicitly during benchmarks so allocation measurements are stable and reproducible across runs.
  - Define per-benchmark thresholds that fail the run if exceeded, catching regressions over time.
  - Benchmarks may be slow; they should not run as part of the standard `test` path. Consider a separate `bench` task or a deeper test tier that can also run in CI on a schedule.

## Blocked / waiting

- [ ] Expand the device test matrix beyond ESP32-S2 once transport tooling is proven.

## Done (recent)

- [x] Rationalize `plans/` folder: remove duplicated prompt files, transform workspace-history into a knowledge document, trim done workstreams, simplify end-of-session checklist.
- [x] Promote MicroPython and CircuitPython CI jobs to required status checks, gated by platform targeting (Decision 0011).
- [x] Validate PR flow and branch protection rulesets end-to-end.
- [x] Deploy docs to GitHub Pages via mike (`docs-deploy.yml`).
- [x] Complete CI/release infrastructure: PyPI trusted publishing (OIDC), all four libraries published to PyPI, single-branch model (Decision 0019), branch protection rulesets enforced.
