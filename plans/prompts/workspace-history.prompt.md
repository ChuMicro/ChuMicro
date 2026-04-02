## Prompt: Capture and extend Chumicro workspace build-up history

Use this prompt when a future session needs to summarize what changed over time, preserve why the workspace looks the way it does, or append a new history checkpoint without losing earlier context.

### Design principles (emerged from the work)

These were not written up front. They surfaced through mistakes, rejected approaches, and user feedback across multiple working sessions:

1. **Auto-discover, don't enumerate.**  Library lists, test paths, coverage sources, lint paths, and PYTHONPATH are all derived from the workspace structure by scanning for `pyproject.toml` under `support/` and `libraries/`. No file should require manual edits when a new library is added.

2. **Zero-config library addition.**  `python scripts/run.py new-library <name>` creates the full directory tree, `pyproject.toml`, `VERSION`, `conftest.py`, `__init__.py`, starter test, and regenerates IDE configs. One command, zero follow-up edits.

3. **No pip-installed dev packages.**  IDE import resolution is handled through source root configuration (`.idea/chumicro.iml` for PyCharm, `pyrightconfig.json` for VS Code). Editable installs (`pip install -e`) were tried and explicitly rejected — they introduce uncertainty about which version of a package the runtime picks up.

4. **Per-library test runs.**  `scripts/run.py test` runs pytest once per package to avoid test-directory collisions (Decision 0009, superseding Decision 0008's `--import-mode=importlib` approach).  Shared test fakes ship as `testing` submodules in `src/`.

5. **Plans and prompts are part of the workspace contract.**  They must stay current with the codebase. After significant implementation or direction changes, update the affected files under `plans/`. These documents exist so that agents and humans can recover context across sessions.

6. **Commit after making changes.**  Don't leave work uncommitted between sessions. Each working session should end with a clean tree.

7. **Simplicity over abstraction.**  Prefer direct function imports over unnecessary classes (`_SystemTicks` was removed because `Heartbeat` only needed the bare functions). Prefer duck typing over ABCs (`TickSource` ABC was removed because `FakeTicks` already implemented the protocol implicitly). Only add indirection when it improves testability or readability.

### Rejected approaches (lessons learned)

These are documented so future sessions don't re-discover them:

1. **Editable pip installs for IDE resolution** — Tried `pip install -e libraries/timing` to make PyCharm resolve imports. Rejected by maintainer: "seems to open windows for uncertainty." The tests already ran correctly from the IDE; only the UI showed unresolved references. Fixed instead by configuring IDE source roots.

2. **Manual `.idea/chumicro.iml` edits** — After updating `.iml` to fix PyCharm imports, the maintainer pointed out this would need manual editing for every new library. Led to the `sync-ide` task, then to the `new-library` scaffolder that calls `sync-ide` automatically.

3. **`__init__.py` in test directories** — Multiple libraries each having `tests/__init__.py` caused pytest to treat them as the same Python package. Manifested as `ImportPathMismatchError`: `('tests.conftest', '.../gpio/tests/conftest.py', '.../timing/tests/conftest.py')`. Fixed by removing `__init__.py` from all `tests/` directories and switching to `--import-mode=importlib`.

4. **Relative mock imports** — `from .mocks.fake_ticks import FakeTicks` broke under importlib mode. Changed to absolute: `from mocks.fake_ticks import FakeTicks`, with each library's `tests/conftest.py` adding the tests directory to `sys.path`.

5. **Hard-coded library lists** — Early versions of `ci/tasks.py` and later `scripts/run.py` had lists like `RUFF_PATHS = [...]` and `SOURCE_PATHS = [...]`. Every new library required editing these lists. Replaced with auto-discovery functions that scan the filesystem.

6. **`TickSource` ABC and `_SystemTicks` class** — The original design used a `TickSource` abstract base class and a `_SystemTicks` implementation. `TickSource` was removed because `FakeTicks` already duck-typed the interface. `_SystemTicks` was later removed because `Heartbeat` used direct function imports (`ticks_ms`, `ticks_diff`) and the class had no other callers.

7. **`ci/tasks.py` as task runner location** — The task runner started in `ci/tasks.py`. Moved to `scripts/run.py` to separate repo-level developer commands from CI-specific helpers. The `ci/` directory now holds only CI-specific scripts (prepare scripts, smoke runners).

### Multi-session working pattern

This workspace has been built across multiple sessions with context losses between them. Key observations:

- Agent sessions can lose context mid-work. The prompts under `plans/prompts/` exist specifically to recover.
- The resume prompt (`workspace-resume.prompt.md`) is the fastest path: it lists what to read, what to check, and what to produce.
- The rebuild prompt (`workspace-rebuild.prompt.md`) has enough detail to recreate the workspace from scratch, including non-obvious technical patterns.
- The history prompt (this file) preserves *why* the workspace looks this way, not just *what* it contains.
- Planning docs (`next-up.md`, `roadmap.md`) should be updated at session end, not deferred.

### Build-up timeline

#### 2026-03-28 — Workspace bootstrap

1. Established Chumicro as a mono-workspace for individually published libraries.
2. Added root planning docs under `plans/`:
   - `README.md`, `roadmap.md`, `next-up.md`
   - `workstreams/`, `decisions/`
3. Recorded accepted decisions for:
   - mono-workspace layout (Decision 0001)
   - initial release strategy (later revised to per-library `VERSION` files on 2026-03-31)
   - test/runtime boundaries (Decision 0003)
4. Added root tooling: `pyproject.toml` with `pytest`, `pytest-cov`, `ruff`.
5. Added the first reusable support package in `support/runtime/`.
6. Added the first GitHub Actions workflow in `.github/workflows/ci.yml`.
7. Kept `venv` as the documented development path for the first phase.

#### 2026-03-29 — First library slice and runtime validation

1. Accepted the first-slice decision for the sample library (Decision 0004):
   - Option B (pure logic + one hardware-facing seam)
   - timing/ticks as the first seam
   - digital I/O deferred as the likely next seam
2. Added `support/test_harness/` as a tiny on-device test runner scaffold.
3. Added `sample/` as the first publishable library slice (later renamed and moved).
4. Implemented the first sample behavior:
   - `Heartbeat` service object
   - runtime-aware tick helpers (`ticks_ms`, `ticks_diff`, `ticks_add`)
   - host tests with `FakeTicks` mock
   - a device-facing timing test
5. Added `ci/tasks.py` as the shared repo-level task entrypoints for `lint`, `test-host`, `build-sample`, `test-micropython-compat`, `test-circuitpython-compat`, and `test-device`.
6. Added `ci/run_sample_device_tests.py` as the first compatibility smoke script.
7. Added `devices.example.yml` and documented the manual-only device validation starting point.
8. Added `ci/prepare_micropython.py` to prepare a pinned repo-local MicroPython unix-port runtime.
9. Verified the sample MicroPython smoke test against the prepared local runtime.
10. Added `ci/prepare_circuitpython.py` and verified a pinned CircuitPython unix-port build on macOS.
11. Switched canonical compatibility runner to `ci/run_sample_device_smoke.py` (Decision 0006).
12. Added advisory GitHub Actions jobs for MicroPython and CircuitPython compatibility.
13. Added `plans/prompts/` for saved planning prompts and workspace build-up history.
14. Accepted Decision 0005 (Windows WSL2 path) and Decision 0006 (shared smoke runner).
15. Accepted Decision 0007 (cross-platform dependency and distribution strategy):
    - Re-implement rather than depend when a library fails the cross-platform test.
    - Publish to PyPI, mip, and circup.
    - IDE completions from type stubs, not Blinka.
    - External dependencies are allowed but the bar is high.

#### 2026-03-30 — Structural reorganization

This phase restructured the workspace to support multiple libraries. The key changes were driven by the realization that `sample/` at the root would not scale.

1. Moved `sample/` into `libraries/sample/` so published libraries live in a dedicated, predictable directory.
2. Removed `VERSION` files from `support/runtime/` and `support/test_harness/` — they are workspace-internal, not published.
3. Scoped publishable-package discovery to `libraries/` only.
4. Renamed `sample` to `timing` (package name `chumicro-timing`, importable as `chumicro_timing`).
5. Removed `TickSource` ABC — `FakeTicks` already duck-typed the interface.
6. Made `SystemTicks` private (`_SystemTicks`) — it was an implementation detail for Heartbeat's default.
7. Moved the task runner from `ci/tasks.py` to `scripts/run.py` to separate developer tasks from CI helpers.
8. Replaced cross-directory imports in the task runner with direct path constants.
9. Updated all CI scripts, pyproject.toml, README, and planning docs to reflect the new layout.
10. Replaced `build-sample` with a generic `build` task that discovers all publishable packages.

#### 2026-03-31 — Version strategy revision

1. Replaced the old PR-label-based release intent guidance with a per-library `VERSION` file strategy (Decision 0002 revised).
2. Updated `AGENTS.md` so agents treat each library's checked-in `VERSION` file as the canonical published version.
3. Updated release planning docs and prompts accordingly.

#### 2026-04-01 — Multi-library foundation

This was the largest single session. It addressed three areas: the workspace was still built around a single library, the IDE couldn't resolve imports reliably, and adding a new library required editing too many files.

**Auto-discovery (replaced all hard-coded lists):**
1. `scripts/run.py` discovers libraries and support packages by scanning for `pyproject.toml`.
2. `pyproject.toml` uses broad `testpaths = ["support", "libraries"]`.
3. Root `conftest.py` auto-discovers source roots and excludes `device_tests/`.
4. Lint paths, coverage sources, test paths, and PYTHONPATH are all derived from structure.

**Scoped test running:**
5. `test-host` default: detect changed packages on branch vs `origin/main`.
6. `--all`: run everything. `--libraries timing`: run specific packages.
7. `-- -k test_name`: pytest passthrough for individual tests.
8. Coverage gate relaxed automatically for partial runs (passthrough args trigger `--cov-fail-under=0`).

**Library scaffolding and IDE config generation:**
9. `new-library <name>` creates full directory structure with `pyproject.toml`, `VERSION`, `confe
