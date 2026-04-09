# Next Up

## Now

- [ ] Enable GitHub Discussions (Q&A, Ideas, Show and Tell categories) — manual step in repo settings.

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

- [x] Contributor experience audit v2: README reorder (Installation before Development setup), dependency graph, cross-library references (timing ↔ runner), "What's new" sections in all library guides, PR template simplification (N/A defaults), coverage hint in `run.py`, `CLAUDE.md` and `.cursorrules` pointers, GitHub Discussions link in CONTRIBUTING.md and issue template config.
- [x] Create CONTRIBUTING.md, contributor sub-guides (first-pr, new-library, releases), and GitHub issue templates (bug report, feature request, stable promotion).
- [x] Rationalize `plans/` folder: remove duplicated prompt files, transform workspace-history into a knowledge document, trim done workstreams, simplify end-of-session checklist.
- [x] Promote MicroPython and CircuitPython CI jobs to required status checks, gated by platform targeting (Decision 0011).
- [x] Validate PR flow and branch protection rulesets end-to-end.
- [x] Deploy docs to GitHub Pages via mike (`docs-deploy.yml`).
- [x] Complete CI/release infrastructure: PyPI trusted publishing (OIDC), all four libraries published to PyPI, single-branch model (Decision 0019), branch protection rulesets enforced.
