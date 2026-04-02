## Prompt: Capture and extend Chumicro workspace build-up history

Use this prompt when a future session needs to summarize what changed over time, preserve why the workspace looks the way it does, or append a new history checkpoint without losing earlier context.

### Current build-up history checkpoint

#### 2026-03-28

1. Established Chumicro as a mono-workspace for individually published libraries.
2. Added root planning docs under `plans/`:
   - `README.md`
   - `roadmap.md`
   - `next-up.md`
   - `workstreams/`
   - `decisions/`
3. Recorded accepted decisions for:
   - mono-workspace layout
   - the initial release strategy (later revised to per-library `VERSION` files on 2026-03-31)
   - test/runtime boundaries
4. Added root tooling in `pyproject.toml` for:
   - `pytest`
   - `pytest-cov`
   - `ruff`
5. Added the first reusable support package in `support/runtime/`.
6. Added the first GitHub Actions workflow in `.github/workflows/ci.yml`.
7. Kept `venv` as the documented development path for the first phase.

#### 2026-03-29

1. Accepted the first-slice decision for the sample library:
   - Option B
   - timing/ticks as the first seam
   - digital I/O deferred as the likely next seam
2. Added `support/test_harness/` as a tiny on-device test runner scaffold.
3. Added `sample/` as the first publishable library slice.
4. Implemented the first sample behavior:
   - `Heartbeat`
   - runtime-aware tick helpers
   - host tests
   - a device-facing timing test
5. Verified repo-wide checks for tests, coverage, lint, and sample package build.
6. Added `plans/prompts/` so useful prompts can preserve rebuild context and workspace history.
7. Updated planning docs so current state, incomplete areas, and next slices match the actual repo.
8. Added durable prompt files for planning refresh, workspace rebuild, and restart-time rehydration.
9. Added `ci/tasks.py` so local development, CI, and future agents can share the same repo-level task entrypoints.
10. Added `ci/run_sample_device_tests.py` as the first checked-in compatibility smoke script for the sample device test.
11. Added `devices.example.yml` and documented the manual-only device validation starting point.
12. Added `ci/prepare_micropython.py` so the workspace can prepare a pinned repo-local MicroPython unix-port runtime for shared testing.
13. Removed runtime-facing postponed annotations that blocked MicroPython imports and verified the sample MicroPython smoke test against the prepared local runtime.
14. Added `ci/prepare_circuitpython.py` and verified a pinned local CircuitPython unix-port build on macOS.
15. Switched the canonical compatibility runner to `ci/run_sample_device_smoke.py`, keeping `ci/run_sample_device_tests.py` as a backward-compatible wrapper.
16. Added advisory GitHub Actions jobs for `test-micropython-compat` and `test-circuitpython-compat`.
17. Accepted Decision 0006 to keep the import-free shared smoke runner as the canonical compatibility baseline for the current workspace phase.

### Still open after this checkpoint

#### 2026-03-31

1. Replaced the old PR-label-based release intent guidance with a per-library `VERSION` file strategy.
2. Updated `Agents.md` so agents treat each library's checked-in `VERSION` file as the canonical published version.
3. Updated the release planning docs and prompts to require PR checks that enforce `VERSION` file edits for release-relevant library changes.
4. Renamed Decision 0002 to `0002-per-library-version-files.md` to match the new direction.

### Still open after this checkpoint

1. Release automation and per-library `VERSION` file enforcement workflows.
2. IDE stub packaging strategy.
3. The second sample seam after timing/ticks.
4. Whether the advisory runtime CI jobs should stay optional or become protected-branch requirements.

#### 2026-04-01

1. Added multi-library foundation: auto-discovery replaces all hard-coded library lists.
   - `scripts/run.py` discovers libraries and support packages by scanning for `pyproject.toml`.
   - `pyproject.toml` uses broad `testpaths = ["support", "libraries"]` and `--import-mode=importlib`.
   - Root `conftest.py` auto-discovers source roots and excludes `device_tests/`.
2. Added scoped test running to `test-host`:
   - Default: detect changed packages on branch vs `origin/main`.
   - `--all`: run everything. `--libraries timing`: run specific packages.
   - `-- -k test_name`: pytest passthrough for individual tests.
   - Coverage gate relaxed automatically for partial runs.
3. Added `new-library` scaffolder (`python scripts/run.py new-library <name>`):
   - Creates full directory structure, `pyproject.toml`, `VERSION`, `conftest.py`, `__init__.py`.
   - Regenerates IDE configs automatically.
4. Added `sync-ide` task that generates:
   - `.idea/chumicro.iml` (PyCharm source roots) from workspace structure.
   - `pyrightconfig.json` (VS Code/Pyright `extraPaths`) from workspace structure.
   - Preserves existing SDK references and user settings.
5. Removed `__init__.py` from library `tests/` directories to avoid module name collisions across libraries when pytest runs `--import-mode=importlib`.
6. Changed mock imports to absolute (`from mocks.fake_ticks import FakeTicks`) with conftest adding the tests dir to `sys.path`.
7. Removed unused `_SystemTicks` class from `chumicro_timing.ticks`.
8. Fixed `.idea/chumicro.iml` source roots (was still pointing at old `sample/` path).
9. Updated CI workflow to use `--all` flag explicitly.
10. Updated `preflight` and `test-runtime-matrix` to always run all tests.
11. `setup` task now calls `sync-ide` to regenerate IDE configs.

### Still open after this checkpoint

1. Release automation and per-library `VERSION` file enforcement workflows.
2. IDE stub packaging strategy.
3. The compatibility smoke runner is still timing-specific — needs generalization for multi-library.
4. Shared cross-library test mocks (e.g., FakeTicks usable from other libraries).
5. The second seam after timing/ticks.
6. Whether the advisory runtime CI jobs should stay optional or become protected-branch requirements.
7. VS Code workspace validation (pyrightconfig.json generated but not tested).
8. Test ergonomics: reducing repeated boilerplate across test files.
9. Prompts under `plans/prompts/` had gone stale and were updated in this checkpoint.

### How to extend this history

1. Add a new dated checkpoint instead of rewriting old ones.
2. Only record work that was actually implemented or explicitly decided.
3. Link to decisions, prompts, and planning docs when they explain the why.
4. Keep the timeline short and factual so future sessions can scan it quickly.
5. When adding a major checkpoint, also update `plans/roadmap.md` and `plans/next-up.md` if the active plan changed.

