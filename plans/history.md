# Workspace History

This document captures *why* the workspace looks the way it does — design
principles that emerged from mistakes, approaches that were tried and rejected,
and the timeline of how things evolved.  Consult it when you need to understand
the reasoning behind a pattern, or to check whether an approach was already
tried.

## Design principles

These were not written up front.  They surfaced through mistakes, rejected
approaches, and user feedback across multiple working sessions:

1. **Auto-discover, don't enumerate.**  Library lists, test paths, coverage sources, lint paths, and PYTHONPATH are all derived from the workspace structure by scanning for `pyproject.toml` under `support/` and `libraries/`. No file should require manual edits when a new library is added.

2. **Zero-config library addition.**  `python scripts/run.py new-library <name>` creates the full directory tree, `pyproject.toml`, `VERSION`, `conftest.py`, `__init__.py`, starter test, and regenerates IDE configs. One command, zero follow-up edits.

3. **No pip-installed dev packages.**  IDE import resolution is handled through source root configuration (`.idea/chumicro.iml` for PyCharm, `pyrightconfig.json` for VS Code). Editable installs (`pip install -e`) were tried and explicitly rejected — they introduce uncertainty about which version of a package the runtime picks up.

4. **Per-library test runs.**  `scripts/run.py test` runs pytest once per package to avoid test-directory collisions (Decision 0009, superseding Decision 0008's `--import-mode=importlib` approach).  Shared test fakes ship as `testing` submodules in `src/`.

5. **Plans and decisions are part of the workspace contract.**  They must stay current with the codebase. After significant implementation or direction changes, update the affected files under `plans/`. These documents exist so that agents and humans can recover context across sessions.

6. **Commit after making changes.**  Don't leave work uncommitted between sessions. Each working session should end with a clean tree.

7. **Simplicity over abstraction.**  Prefer direct function imports over unnecessary classes (`_SystemTicks` was removed because `Heartbeat` only needed the bare functions). Prefer duck typing over ABCs (`TickSource` ABC was removed because `FakeTicks` already implemented the protocol implicitly). Only add indirection when it improves testability or readability.

## Rejected approaches

These are documented so future sessions don't re-discover them:

1. **Editable pip installs for IDE resolution** — Tried `pip install -e libraries/timing` to make PyCharm resolve imports. Rejected by maintainer: "seems to open windows for uncertainty." The tests already ran correctly from the IDE; only the UI showed unresolved references. Fixed instead by configuring IDE source roots.

2. **Manual `.idea/chumicro.iml` edits** — After updating `.iml` to fix PyCharm imports, the maintainer pointed out this would need manual editing for every new library. Led to the `sync-ide` task, then to the `new-library` scaffolder that calls `sync-ide` automatically.

3. **`__init__.py` in test directories** — Multiple libraries each having `tests/__init__.py` caused pytest to treat them as the same Python package. Manifested as `ImportPathMismatchError`: `('tests.conftest', '.../gpio/tests/conftest.py', '.../timing/tests/conftest.py')`. Fixed by removing `__init__.py` from all `tests/` directories and switching to `--import-mode=importlib`.

4. **Relative mock imports** — `from .mocks.fake_ticks import FakeTicks` broke under importlib mode. Changed to absolute: `from mocks.fake_ticks import FakeTicks`, with each library's `tests/conftest.py` adding the tests directory to `sys.path`.

5. **Hard-coded library lists** — Early versions of `ci/tasks.py` and later `scripts/run.py` had lists like `RUFF_PATHS = [...]` and `SOURCE_PATHS = [...]`. Every new library required editing these lists. Replaced with auto-discovery functions that scan the filesystem.

6. **`TickSource` ABC and `_SystemTicks` class** — The original design used a `TickSource` abstract base class and a `_SystemTicks` implementation. `TickSource` was removed because `FakeTicks` already duck-typed the interface. `_SystemTicks` was later removed because `Heartbeat` used direct function imports (`ticks_ms`, `ticks_diff`) and the class had no other callers.

7. **`ci/tasks.py` as task runner location** — The task runner started in `ci/tasks.py`. Moved to `scripts/run.py` to separate repo-level developer commands from CI-specific helpers. The `ci/` directory was later removed entirely once all logic moved into `scripts/`.

8. **Event-based runner pattern** — The initial `chumicro-runner` implementation used an event bus: components emitted `Event` objects into an `EventQueueSink`, and a `SimpleEventDispatcher` routed them by event type.  This required significant ceremony for simple cases.  Replaced with a gate-based `check(now_ms) -> bool` contract (Decision 0014 revised).

9. **Symlinks and hooks for shared CSS** — Attempted to deduplicate `extra.css` across libraries via symlinks (zensical doesn't follow symlinks) and MkDocs hooks (zensical doesn't support hooks). Both failed. Briefly switched to Material `scheme: default` (light) to avoid the problem, then restored dark theme (`scheme: slate`) once the deduplication was solved via build-time copy: `support/docs/extra.css` is the single source of truth, copied into each library's `docs/stylesheets/` by the build task and gitignored.

10. **Two-branch model (`develop` + `main`)** — Auto-syncing pushed all library code to `main` even for libraries that hadn't been individually promoted, so `main` didn't actually reflect stable releases. Revised to single-branch model: `main` is the only branch, stable releases are tag-based (Decision 0019 revised).

11. **Setuptools as build backend** — Leaked `.egg-info` directories into published sdists — a known, unfixable quirk of setuptools. Switched to hatchling. Separately, hatchling's default sdist includes all VCS-tracked files, which leaked tests, docs, and examples into PyPI packages. Required explicit `[tool.hatch.build.targets.sdist]` include filters to ship only `src/`, `VERSION`, and `README.md`.

12. **MkDocs** — MkDocs 1.x was unmaintained (18 months without releases) and MkDocs 2.0 broke all plugins/themes with no migration path. Switched to Zensical (from the Material for MkDocs team, reads existing `mkdocs.yml` natively, near-instant builds via Rust core). Zero config changes required.

13. **ReadTheDocs for docs hosting** — Requires a paid Business plan ($50/month) for private repos. GitHub Pages is free, deploys from GitHub Actions (already in place), and works naturally with the mono-repo layout. Versioned docs via `mike` with per-library `--deploy-prefix`.

14. **VERSION-triggered auto-releases** — Originally `release.yml` fired automatically on VERSION file pushes. Provided no control over release timing during pipeline validation. Burned PyPI versions 0.1.0 and 0.1.2 for `chumicro-timing` (uploaded then yanked). Switched to manual `workflow_dispatch`, then to the current model where VERSION bumps on `main` auto-publish experimentals but stable requires explicit promotion via `promote.yml`.

15. **PAT-based bundle repo push** — `BUNDLE_TOKEN` (PAT) was the initial auth for pushing to bundle repos. When branch protection was enabled, PATs couldn't bypass rules cleanly. Switched to per-repo SSH deploy keys (single-repo scoped, least privilege). PAT retained only for GitHub API calls (`gh release create`).

16. **Single bundle repo for both channels** — Initially both stable and experimental packages lived in the same repo with `_experimental`-suffixed directories. circup's `Bundle.latest_tag` follows `/releases/latest`, which only returns non-prerelease tags — experimental releases were invisible. Split into two repos (`ChuMicro-Bundle` and `ChuMicro-Bundle-Experimental`). Original repos were recreated with new names after PII exposure.

17. **CodeRabbit for AI code review** — Added `.coderabbit.yaml` initially, removed before any PRs used it. Deferred AI review tooling until external contributions begin.

## Key technical patterns

These patterns caused real bugs when implemented incorrectly. Follow them exactly.

### Per-library test runs (Decision 0009)

- `scripts/run.py test` runs a separate pytest subprocess for each package.
- Each run targets a single library's `tests/` directory — no collision between identically named directories.
- `PYTHONPATH` is set to include all `src/` directories so cross-library imports work.
- Each library must independently meet the 94% coverage threshold.  Coverage data is written per-library (`.coverage.<name>`), then `coverage combine` merges them for a combined report.
- This replaced `--import-mode=importlib` (Decision 0008, now superseded) which imposed constraints on test directory structure.
- Bare `pytest` from the repo root is not the supported path — use `run.py test`.

### Shared test fakes

- Test fakes ship with the library they mock as a `testing` submodule (e.g., `chumicro_timing.testing.FakeTicks`).
- Other libraries import them directly: `from chumicro_timing.testing import FakeTicks`.
- This follows the standard Python pattern (`django.test`, `flask.testing`).
- No `tests/mocks/` directory is needed; the fake lives in `src/` alongside the production code.

### Root conftest auto-discovery

- Root `conftest.py` scans `support/*/src` and `libraries/*/src` for source roots.
- Adds them to `sys.path` so IDE "run single test" and direct pytest invocations can import library packages.
- Sets `collect_ignore_glob = ["**/functional_tests/**"]` to exclude functional tests.
- `run.py test` sets PYTHONPATH independently, so the root conftest is a convenience, not a requirement for the test runner.

### IDE config generation (sync-ide)

- `python scripts/run.py sync-ide` generates five outputs from workspace structure:
  - `.idea/chumicro.iml` — adds `<sourceFolder>` entries for each `src/` and `tests/` directory.
  - `.idea/runConfigurations/` — per-task XML run configs (preflight, test, lint, etc.).
  - `pyrightconfig.json` — sets `extraPaths` for each `src/` directory.
  - `.vscode/tasks.json` — VS Code task definitions mirroring `run.py` commands.
  - `.vscode/settings.json` — `python.analysis.extraPaths` for Pylance resolution.
- Called automatically by `setup` and `new-library`.
- The `.iml` generator preserves existing non-source-folder content (SDK settings, etc.) and only replaces the source folder entries.
- **No manual IDE config editing is needed when adding libraries.**

### No editable pip installs for workspace packages

- IDE import resolution uses source root configuration, not editable installs.
- `pip install -e` was tried and explicitly rejected.
- Third-party dev dependencies (`pytest`, `ruff`, `circuitpython-stubs`, `micropython-esp32-stubs`, etc.) are pip-installed normally — this is a different category.
- The root conftest handles `sys.path` for IDE test runs; `run.py` handles it via PYTHONPATH for CLI runs.

## Build-up timeline

### 2026-03-28 — Workspace bootstrap

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

### 2026-03-29 — First library slice and runtime validation

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
5. Added `ci/tasks.py` as the shared repo-level task entrypoints.
6. Added `devices.example.yml` and documented the manual-only device validation starting point.
7. Added `ci/prepare_micropython.py` to prepare a pinned repo-local MicroPython unix-port runtime.
8. Verified the sample MicroPython smoke test against the prepared local runtime.
9. Added `ci/prepare_circuitpython.py` and verified a pinned CircuitPython unix-port build on macOS.
10. Added advisory GitHub Actions jobs for MicroPython and CircuitPython compatibility.
11. Added `plans/prompts/` for saved planning prompts and workspace build-up history.
12. Accepted Decisions 0005 (Windows WSL2 path), 0006 (shared smoke runner), 0007 (cross-platform dependency strategy).

### 2026-03-30 — Structural reorganization

This phase restructured the workspace to support multiple libraries. The key changes were driven by the realization that `sample/` at the root would not scale.

1. Moved `sample/` into `libraries/sample/` so published libraries live in a dedicated, predictable directory.
2. Removed `VERSION` files from `support/runtime/` and `support/test_harness/` — they are workspace-internal, not published.
3. Scoped publishable-package discovery to `libraries/` only.
4. Renamed `sample` to `timing` (package name `chumicro-timing`, importable as `chumicro_timing`).
5. Removed `TickSource` ABC — `FakeTicks` already duck-typed the interface.
6. Made `SystemTicks` private (`_SystemTicks`) — it was an implementation detail for Heartbeat's default.
7. Moved the task runner from `ci/tasks.py` to `scripts/run.py`.
8. Updated all CI scripts, pyproject.toml, README, and planning docs to reflect the new layout.

### 2026-03-31 — Version strategy revision

1. Replaced the old PR-label-based release intent with per-library `VERSION` file strategy (Decision 0002 revised).

### 2026-04-01 — Multi-library foundation

This was the largest single session. It addressed three areas: the workspace was still built around a single library, the IDE couldn't resolve imports reliably, and adding a new library required editing too many files.

**Auto-discovery:** Replaced all hard-coded lists. `scripts/run.py` discovers packages by scanning for `pyproject.toml`. Root `conftest.py` auto-discovers source roots.

**Scoped test running:** Branch-diff detection, `--all`, `--libraries`, library-scoped `-k` filtering. Coverage gate relaxed automatically when `-k` is used.

**Library scaffolding and IDE config generation:** `new-library` creates full directory structure. `sync-ide` generates IDE configs from workspace structure.

**Test isolation evolution:** Decision 0008 (importlib mode) → Decision 0009 (per-library pytest runs). `FakeTicks` moved from `tests/mocks/` to `src/chumicro_timing/testing.py`. Per-library 90% coverage threshold. Decision 0010 (library testability patterns).

### 2026-04-02 — Platform targeting, stubs, docs, and runner pattern

**Platform targeting (Decision 0011):** Libraries can declare `[tool.chumicro].platforms` in `pyproject.toml`.

**IDE type stubs (Decision 0012):** Upstream `circuitpython-stubs` and `micropython-esp32-stubs` from PyPI, version-pinned to `target-runtimes.toml`.

**Docs and examples (Decision 0013):** MkDocs + Material + mkdocstrings. Required `guide.md` section structure. Example import-verification in preflight.

**Runner pattern (Decision 0014):** Gate-based `check(now_ms) -> bool` contract. `chumicro-runner` library with `Runner`, `TaskHandle`, `CallRecorder`.

### 2026-04-03 — Serviceable audit, board architecture, script modularization

**Serviceable library audit:** Verified `collections.deque` API across all three runtimes using pinned source trees.

**Board architecture support (Decision 0015):** Source-level audit of `CIRCUITPY_FULL_BUILD` and `MICROPY_CONFIG_ROM_LEVEL` across all ports. Tier 1/2/unsupported classification.

**Script modularization:** Split `scripts/run.py` into focused modules: `discovery.py`, `ide.py`, `scaffold.py`, `prepare.py`, etc. Removed `ci/` directory entirely.

**Cross-runtime unit tests (Decision 0016):** Compat tasks now run real unit tests from `tests/` through the lightweight harness, not just smoke checks.

### 2026-04-04 — Runner simplification, compat, msgpack, bundles

**Runner simplification (Decision 0014 revised):** Removed event-based path entirely. Service contract changed to `check(now_ms) -> bool`.

**chumicro-compat library:** `functools.partial` polyfill for MicroPython/CircuitPython.

**chumicro-msgpack library:** Pure-Python MessagePack encoder/decoder with native CircuitPython C delegation.

**Distribution bundle decision (Decision 0018):** Separate `ChuMicro/ChuMicro-Bundle` distribution repo for built artifacts.

**CircuitPython RingIO bug (Decision 0017):** Traced why CI never hits the RingIO linker error. Documented workaround.

**Board baseline lowered (Decision 0015 revised):** 512 KB → 256 KB MCU RAM to support RP2040.

### 2026-04-05 — CI/release infrastructure completed

**Build backend switch:** Setuptools → hatchling to eliminate `.egg-info` leakage in sdists. Then discovered hatchling's default sdist includes all VCS-tracked files — added explicit include filters (0.1.8) after 0.1.7 shipped with tests/docs in the package.

**PyPI publishing iterations:** OIDC trusted publishing required a `pypi` environment in GitHub repo settings (the OIDC token was missing the environment claim). First successful publish was 0.1.2 for timing, then yanked. Switched to manual releases, reset all versions to 0.1.0, then iterated to the current model.

**Bundle repo iterations:** Traced circup source code (`Bundle` class, `shared.py`, `command_utils.py`) to discover two zip format bugs: (1) internal directory structure must be `{bundle_id}-{platform}-{tag}/lib/`, not bare `lib/`; (2) mpy zip names must match circup's PLATFORMS values ("10.x-mpy"). circup falls back to `.py` source when mpy zips are missing. Original bundle repos recreated with new names (`ChuMicro-Bundle`) after PII exposure.

**Release pipeline:** Release workflow with PyPI trusted publishing, git tags, GitHub Releases, bundle repo publishing. Promote workflow for stable releases. All four libraries published to PyPI.

**Decisions 0019 (branching model) and 0020 (API breakage detection).**

**Script hardening:** Comprehensive deduplication audit across `scripts/`. Added `find_package_dir()` as single source of truth, consolidated runtime compat test helpers, replaced env vars with CLI arguments (`--micropython-bin`, `--circuitpython-bin`, `--matrix`). Lowered Python version floor from 3.11 to 3.9 with `tomli` backport.

**Platform targeting wired:** `[tool.chumicro].platforms` reader implemented. Cross-runtime compat runners filter by platform.

### 2026-04-06 — Branching model revision, docs, Milestone 2 completion

**Single-branch model (Decision 0019 revised):** `main` is the only branch. Experimental auto-publishes on VERSION bump; stable releases are tag-based via `promote.yml`.

**Docs:** Switched from MkDocs to Zensical (Rust-based, same team as Material). Chose GitHub Pages over ReadTheDocs ($50/month for private repos). Versioned docs via `mike` with per-library `--deploy-prefix`. Dark theme restored (`scheme: slate`) with build-time CSS copy from `support/docs/extra.css`. Auto-generated landing page. Favicons. `docs-preview` command.

**Promote workflow evolution:** Initially `promote.yml` fired `release.yml` via `workflow_dispatch`. Reworked to use `workflow_call` so the full build/publish/tag/bundle work is visible in a single workflow run. Fixed a concurrency deadlock where promote and release both held the same lock via concurrency groups.

**CI hardened:** Runtime compat checks promoted to required. Per-repo SSH deploy keys for bundle repos. `label-check` CI job removed.

**Milestone 2 marked done.** All CI/release exit criteria met.

**All libraries bumped to 0.1.15 (current).**

### 2026-04-07 — Plans rationalization

**Duplication diagnosis:** The `plans/` folder had ~950 lines of duplicated content spread across 7 prompt files, 3 completed workstreams, and bloated done-item lists. The same content (decision lists, command lists, repo shape, "current verified state") was repeated 3–4 times, creating a maintenance treadmill. Two meta-prompts (`plans-sync`, `end-of-session` §5b–5d) existed solely to fight staleness caused by the duplication.

**Resolution:** Deleted 7 prompt files and 3 completed workstreams (462 insertions, 2006 deletions). Transformed `workspace-history.prompt.md` into `history.md` (this document) as a durable knowledge base. Created `end-of-session.md` as a simplified checklist. Moved `guide-generation.prompt.md` to `plans/guide-generation.md`. Trimmed `next-up.md` (90 Done items → 5 recent) and `roadmap.md` (done milestones collapsed). Cross-referenced ~250 commit messages against the remaining plans to surface knowledge gaps.

**Principle:** Plans should capture knowledge that lives in people's heads — design principles, rejected approaches, why decisions were made. Reference material (command lists, decision indices, repo structure) belongs in AGENTS.md and decisions, not duplicated across prompts.

