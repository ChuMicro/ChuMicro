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

7. **`ci/tasks.py` as task runner location** — The task runner started in `ci/tasks.py`. Moved to `scripts/run.py` to separate repo-level developer commands from CI-specific helpers. The `ci/` directory was later removed entirely once all logic moved into `scripts/`.

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
3. Root `conftest.py` auto-discovers source roots and excludes `functional_tests/`.
4. Lint paths, coverage sources, test paths, and PYTHONPATH are all derived from structure.

**Scoped test running:**
5. `test` default: detect changed packages on branch vs `origin/main`.
6. `--all`: run everything. `--libraries timing`: run specific packages.
7. `-k library/test` or `-k library/file/test`: library-scoped test filtering (plain names rejected).
8. Coverage gate relaxed automatically when `-k` is used or `--no-cov` skips coverage entirely.

**Library scaffolding and IDE config generation:**
9. `new-library <name>` creates full directory structure with `pyproject.toml`, `VERSION`, `conftest.py`, `__init__.py`, and README.
10. `sync-ide` generates `.idea/chumicro.iml` (PyCharm) and `pyrightconfig.json` (VS Code) from workspace structure.
11. Both `setup` and `new-library` call `sync-ide` automatically.

**Test isolation evolution:**
12. Added Decision 0008 (`--import-mode=importlib`) as the first multi-library test isolation approach.
13. Moved `FakeTicks` from `tests/mocks/` to `src/chumicro_timing/testing.py` — a `testing` submodule that ships with the library for cross-library reuse.
14. Replaced importlib mode with per-library pytest runs (Decision 0009, superseding 0008) — `scripts/run.py test` runs a separate pytest subprocess per package, then combines coverage.
15. Enforced per-library 90% coverage threshold (previously combining at the end masked individual libraries with low coverage).
16. Renamed `test-host` → `test` — the `host` qualifier was unnecessary jargon.
17. Formalized library testability patterns as Decision 0010: constructor injection, `testing` submodules for fakes, don't mock what you don't own.

#### 2026-04-02 — Cleanup, platform targeting, stubs, docs, and runner pattern

**Cruft removal:**
1. Deleted `ci/run_sample_device_tests.py` (backward-compat wrapper with no callers).
2. Deleted empty `.github/copilot-instructions.md` (AGENTS.md is the source).
3. Removed stale `sample/src` from `.vscode/settings.json` extraPaths.
4. Removed unused `_test_paths_for()` from `run.py`.
5. Simplified per-library conftest files (root conftest handles discovery).
6. Removed `doc/` directory boilerplate from the scaffold and timing library.
7. Fixed stale references across all planning docs: `ci/tasks.py`, `run_sample_device_tests.py`, `doc/`, importlib mode, `tests/mocks/`.

**Platform targeting:**
8. Accepted Decision 0011 (per-library platform targeting): libraries can declare `[tool.chumicro].platforms` in `pyproject.toml` to restrict which runtimes they target. Default (absent) = all three. Gates release automation and cross-runtime compatibility runners.
9. Updated all prompt files and plans/README.md to reference Decision 0011.

**IDE type stubs:**
10. Accepted Decision 0012 (IDE type stubs): use upstream `circuitpython-stubs` and `micropython-esp32-stubs` from PyPI, version-pinned to `runtime-versions.toml`.
11. Consolidated runtime version pins into a single `runtime-versions.toml` file.

**Docs and examples standards:**
12. Accepted Decision 0013 (docs and examples standards): MkDocs + Material + mkdocstrings for API reference (static analysis, no imports needed). Required `guide.md` section structure. Example import-verification in preflight.
13. Added `verify-examples` and `docs` tasks to `scripts/run.py`.
14. Timing library got user guide, API reference, testing helpers docs, and three runnable examples.
15. New-library scaffolder generates `mkdocs.yml`, `docs/api.md` with autodoc, `docs/guide.md` template, and example with `__main__` guard.
16. Later: strengthened Decision 0013 with strict `guide.md` section requirements, `api.md` autodoc rules (no hand-written member lists), and an AI generation prompt at `plans/prompts/guide-generation.prompt.md`.

**Runner pattern:**
17. Accepted Decision 0014 (runner pattern): standardize how active components communicate events. Components implement `check(now_ms) -> bool`, a shared `EventQueueSink` collects events, `Runner` dispatches.
18. New library: `chumicro-runner` 0.1.0 with `Event`, `EventQueueSink`, `SimpleEventDispatcher`, `Runner`, and `FakeEventSink` testing helper. 100% test coverage.
19. `Heartbeat` gained `check(now_ms) -> bool` and `EVENT_TICK` (timing 0.1.0 → 0.2.0, backward compatible). Duck-typed — timing does not import from runner.
20. Serviceable library is pending maintainer audit (tracked in next-up.md).  *(Completed 2026-04-03 — see below.)*

#### 2026-04-03 — Serviceable audit, board architecture decision, AGENTS.md .tools docs

**Serviceable library audit (Decision 0014 — completed):**
1. Verified `collections.deque` API compatibility across all three runtimes by inspecting the pinned source trees under `.tools/`:
   - Constructor: `deque((), maxlen)` works positionally on CPython, MicroPython, and CircuitPython.
   - `len()` and `bool()`: both runtimes implement `MP_UNARY_OP_LEN` and `MP_UNARY_OP_BOOL`.
   - `deque.clear()`: compiled out (`#if 0`) on both MP and CP — but `EventQueueSink.clear()` already uses a `while/popleft()` drain loop, so this was already handled correctly.
   - `deque.append()` / `popleft()`: core operations, available everywhere.
2. Added `FLAG_CHECK_OVERFLOW` support: `EventQueueSink.__init__` now tries `deque((), max_size, 1)` first (MP/CP overflow protection), falling back to `deque((), max_size)` on CPython. The manual `len()` check in `emit()` remains as the primary guard; the overflow flag is a C-level safety net.
3. Marked the audit item as done in `next-up.md`.

**Board architecture support (Decision 0015):**
4. Performed a source-level audit of `CIRCUITPY_FULL_BUILD` and `MICROPY_CONFIG_ROM_LEVEL` across all ports in both pinned source trees.
5. Recorded Decision 0015 with full per-port tables: supported (ESP32 family, RP2040/RP2350, STM32, broadcom, etc.) vs unsupported (SAMD21, most nRF52, MicroPython `minimal`). SAMD51 is a notable edge case — supported on MicroPython but CircuitPython's `atmel-samd` port disables `deque` for the entire port.
6. Updated AGENTS.md "Board Considerations & Feature Detection" section with a summary and link to Decision 0015.

**AGENTS.md — local source clones documentation:**
7. Added "Local source clones (`.tools/`)" content to the "Reference Implementations" section. Explains the directory layout, that `.tools/` requires `prepare-micropython`/`prepare-circuitpython` to exist, and that web search is an acceptable fallback when the directory is missing.
8. Merged the `.tools/` subsection into the Reference Implementations paragraph to eliminate duplication (the original paragraph pointed to GitHub repos while the subsection said to browse locally).
9. Updated `workspace-rebuild.prompt.md` to include `.tools/` in the repo shape and Decision 0015 in the required decisions list.
10. Fixed the stale `next-up.md` sub-bullet that described `EventQueueSink._items` as "a Python-level ring buffer on a pre-allocated list" — it already uses `deque`.

**Git-commit instruction file:**
11. Added `.github/skills/git-commit/SKILL.md` enforcing `git commit -F` via a scratch file instead of `git commit -m`, which broke on zsh special characters.
12. Updated AGENTS.md to reference the instruction file instead of inline commit-mechanics advice.

**Script modularization and `ci/` removal:**
13. Split `scripts/run.py` (~970 lines) into focused modules: `discovery.py` (package discovery, scope parsing, change detection), `ide.py` (IDE config generation), `scaffold.py` (library scaffolding), `prepare.py` (shared build helpers, binary resolution, runtime versions), `prepare_micropython.py`, `prepare_circuitpython.py`, `prepare_workspace.py`. `run.py` is now a slim dispatch-and-task file.
14. Moved prepare logic from `ci/prepare_*.py` into `scripts/` as importable modules.
15. Removed `ci/` directory entirely — all logic now lives in `scripts/`.
16. Moved smoke runner from `ci/` to `support/test_harness/run_device_smoke.py`.
17. Generalized the compatibility smoke runner to discover and exercise device tests for all libraries, not just timing.
18. Dropped `_` prefix from script modules (e.g., `_discovery.py` → `discovery.py`) — the `_` convention was not needed since `scripts/` is not an importable package.
19. Centralized `VERSIONS` dict (from `runtime-versions.toml`) into `prepare.py` so all modules share one parse.

**Task runner CLI improvements:**
20. Replaced hand-rolled `parse_scope_args` with `argparse` subcommands. Each task has its own parser with proper help text.
21. Renamed `test-host` → `test` (the `host` qualifier was unnecessary jargon). Added `--no-cov`, `-x`/`--exitfirst`, and `-v`/`--verbose` as declared CLI arguments.
22. Replaced opaque `--` pytest passthrough with declared `-k` argument using library-scoped syntax: `-k timing/test_heartbeat`, `-k timing/test_ticks/test_add`, or comma-separated multi-library filters.
23. Added `uv` auto-detection: `prepare_workspace.py` and `run.py setup` prefer `uv pip install` and `uv venv` when `uv` is on PATH, falling back to `pip`/stdlib `venv`.
24. Hardened `prepare_workspace.py` to refuse running when `sys.prefix == sys.base_prefix` (system Python without venv).
25. Removed conda from documented environment paths.

**Cross-runtime unit tests (Decision 0016):**
26. Renamed `device_tests/` to `functional_tests/` across all libraries. `functional_tests/` is for real-device tests only; `tests/` is shared between pytest and the lightweight harness.
27. Compat tasks (`test-micropython-compat`, `test-circuitpython-compat`) now run `tests/` through the lightweight harness, not just import-level smoke checks from `functional_tests/`. Supersedes Decision 0006.
28. Cross-runtime tests use plain `assert` and `raises()` from the test harness. `import pytest` is the automatic portability boundary — files that fail to import are logged as SKIP.
29. `_pytest` suffix convention for CPython-only test files (e.g., `test_ticks_pytest.py`). Cross-runtime is the default.
30. Updated Decision 0003 (test pyramid) to reflect the new required middle tier. Marked Decision 0006 as superseded.

#### 2026-04-04 — Serviceable simplification, chumicro-compat library, decision compaction

**chumicro-compat library:**
1. New library: `chumicro-compat` with lightweight `abc` module (ABC base class, `@abstractmethod` decorator).  Uses `__init_subclass__` + `__new__` enforcement — no metaclasses.  Works on MicroPython ≥1.19.1, CircuitPython ≥8.x.  12 tests, 100% coverage.

**Serviceable simplification (Decision 0014 revised):**
2. Removed the event-based path entirely: `Event`, `EventQueueSink`, `SimpleEventDispatcher`, `HandlerHandle`, priority constants all deleted.
3. Service contract changed from `service(event_sink, now_ms)` to `check(now_ms) -> bool` — a gate-based check function that decides IF the handler fires.
4. `Runner` simplified to `(ticks=None)` constructor.  Four registration patterns: object-based (`.service`/`.handle`), callable check + handler, handler-only, and periodic.
5. `FakeEventSink` replaced by `CallRecorder` in testing module.
6. Examples rewritten with real-world concepts: temperature sensor, LED blink, motion detector.
7. `chumicro-runner` 0.1.0 → 0.4.0 (three breaking changes collapsed into one session).

**Decision compaction:**
8. Compacted Decisions 0017 (shared timestamps), 0018 (dispatcher evolution), 0019 (period on runner), 0020 (simplify to gate-based) into a revised Decision 0014.  Four rapid-iteration decision documents were conversational stepping stones, not durable decisions.
9. Updated references in `next-up.md`, `roadmap.md`, and `timing-library.md` workstream.

#### 2026-04-04 (cont.) — CircuitPython unix port investigation, RingIO bug documentation

**CircuitPython RingIO build bug (Decision 0017):**
1. Investigated `tools/ci.sh` in the CircuitPython 10.1.4 source tree. Confirmed it is dead code — inherited from MicroPython, never referenced by any CircuitPython GitHub Actions workflow.
2. Traced why CI never hits the RingIO linker error: `.github/workflows/run-tests.yml` builds `VARIANT=coverage`, and `ports/unix/variants/coverage/mpconfigvariant.h:52` explicitly sets `MICROPY_PY_MICROPYTHON_RINGIO (0)`.
3. Full-tree search confirmed CircuitPython never uses RingIO: zero references in `shared-bindings/`, `shared-module/`, `ports/`, `py/circuitpy_mpconfig.h`, `py/circuitpy_defns.mk`, or tests. RingIO is a MicroPython-only ISR-to-main-loop ring buffer — irrelevant in CP's ISR-free architecture.
4. Recorded findings as Decision 0017 (`plans/decisions/0017-circuitpython-ringio-bug.md`).

**Coverage vs standard variant analysis:**
5. Evaluated switching to `VARIANT=coverage` for cross-runtime testing. Rejected:
   - Coverage disables `struct` (`MICROPY_PY_STRUCT (0)`) — unavailable on unix port since shared-bindings aren't built, but works on real boards.
   - Coverage enables `EVERYTHING`-level features not available on real ESP32 boards (`namedtuple._asdict`, `marshal`, `re` match groups, etc.).
   - Memory/perf profiling APIs (`gc.mem_alloc`, `micropython.mem_current/mem_peak`, `heap_lock/unlock`, `time.ticks_us`, `mem_info` with block maps) are fully available on the `standard` variant via `mpconfigvariant_common.h`. Coverage adds only `sys.getsizeof` and `micropython.heap_locked` — neither essential.
6. Confirmed `VARIANT=standard` + `-DMICROPY_PY_MICROPYTHON_RINGIO=0` remains the correct configuration.

**CircuitPython README testing instructions:**
7. Validated that the README testing instructions the user found (`make axtls`, `make micropython`) are outdated/incorrect. `make axtls` doesn't exist as a target in either CP or MP unix ports. CP explicitly disables SSL (`MICROPY_PY_SSL = 0`). The correct test command is `make -C ports/unix test VARIANT=standard`.

