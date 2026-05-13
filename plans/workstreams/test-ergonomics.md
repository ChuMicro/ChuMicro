# Workstream: Test Ecosystem Ergonomics

Status: **open** — audited 2026-05-12, five phases scoped, none started.

## Purpose

Three years of test growth, 3,858 tests, 64,508 LOC, 885 `monkeypatch` calls.  The libraries-side test surface is already lean (constructor injection works, 12 `testing.py` modules in use, only 58 `monkeypatch` calls across all 16 device libraries combined).  The workbench-side test surface is not — 755 of 885 `monkeypatch` calls live in `workbench/*/tests/`, and the two largest workbench packages (`workspace`, `pytest-device`) have **no `testing.py` module at all**, so every test file inlines its own fakes.  The structural fix is asymmetric: workbench needs both new `testing.py` modules and constructor-injection refactors to production code; libraries need a small handful of shared helpers and stay cross-runtime-safe.

## Audit findings

### Quantified state (2026-05-12)

| Tree | Test LOC | Tests | LOC/test | `monkeypatch` calls |
|---|---|---|---|---|
| `libraries/` (16 packages, all cross-runtime) | ~25,000 | 1,412 | 13–23 | **58** |
| `workbench/` (5 packages, CPython-only) | ~37,000 | 2,229 | 8–18 | **755** |

Worst LOC/test ratios: `libraries/sockets` 23, `workbench/deploy` 18, `workbench/workspace` 17, `libraries/mqtt` 17, `workbench/pytest-device` 17, `libraries/runner` 16.  Canonical lean libraries (`compat`, `events`, `logging`) are 9–10 LOC/test.

Largest single files: `workbench/workspace/tests/test_cli.py` (5,967 LOC), `workbench/deploy/tests/test_circuitpython_transport.py` (3,409 LOC), `libraries/requests/tests/test_requests.py` (2,011 LOC).

### Finding 1 — workbench/workspace has no testing.py (421 monkeypatches across 26 test files)

`workbench/workspace/src/chumicro_workspace/` ships no `testing.py` submodule.  Tests therefore inline:

- `_FakePort(device, description)` redefined at `workbench/workspace/tests/test_cli.py:635, 2264, 2278, 2297` — four copies of the same 4-line `pyserial.tools.list_ports` shim.
- `def fake_run(args, **kwargs)` capturing-to-list lambda redefined at `test_cli.py:156-159, 263-266, 1910-1918` — 8+ identical 4-6 line skeletons, mostly returning `CompletedProcess(args, 0)`.
- `_Info()` probe-result builder, `_MockEntry` device-entry shim — inlined ad hoc per test.
- `_seed_workspace(tmp_path, **overrides)` / `_seed_project(tmp_path, **overrides)` — 410 call sites across 26 files, each writing the same TOML/YAML scaffold inline.

This is the largest single concentration of test boilerplate in the workspace.

### Finding 2 — workbench/pytest-device has no testing.py (30 monkeypatches, 10+ inlined fakes)

`workbench/pytest-device/src/chumicro_pytest_device/` ships no `testing.py` submodule.  Tests inline:

- `_make_prepare_item()`, `_make_run_file_item()`, `_make_test_item()` at `tests/test_plugin.py:1019-1047` — three helpers masquerading as factory functions.
- `_stub_config()`, `_stub_session()` at `test_plugin.py:1502-1642` — nested classes with `__init__` shims.
- `FakePrepareItem` / `FakeRunFileItem` at `test_plugin.py:877-920` — one-off duplicates of the package's own classes.

### Finding 3 — Most monkeypatch.setattr targets point at production code that should accept constructor injection

Top targets (workbench-wide):

| Target | Patches | Diagnosis |
|---|---|---|
| `cli.subprocess.run` (deploy + workspace) | 15+ | CLI command objects should take a `subprocess_runner` callable |
| `chumicro_deploy.circuitpy_drive._circuitpy_volume_candidates` | 13 | `Deployer` should accept a `drive_scanner` callable; the fake already exists in `chumicro_deploy.testing` but production code doesn't accept the injection |
| `onboarding._UF2_MOUNT_SEARCH_PATHS` | 22 | Module-level constant should move to an injected config dataclass |
| `chumicro_deploy.cli.flash_firmware` | 4 | CLI dispatch should inject the flash function |
| `chumicro_repl.tail` | 12 | Already exposed via testing.py; test_cli should import the fake, not patch the symbol |

The remaining ~6 targets (`sys.platform`, `sys.stdin.isatty()`, `sys.stderr.isatty()`) are legitimate test-only seams — they guard runtime environment branches that have no business being constructor-injected.

### Finding 4 — `_connect()` indirection masks host-state dependencies (audit's anchor)

`workbench/deploy/tests/test_circuitpython_transport.py` defines a `_connect(drive_path=..., monkeypatch=...)` helper (line 1811) used by 40+ tests in the file.  The 2026-05-12 preflight-timing investigation discovered that 6 of those tests silently depended on a real `/Volumes/CIRCUITPY` drive being present on the host — the indirection hid that contract.  An explicit `with_circuitpy_drive(tmp_path)` context manager would make per-test drive-dependence visible at the call site.  Pre-requisite already in place: `isolate_from_host_filesystem` in `chumicro_deploy.testing` (2026-05-12) is the working precedent.

### Finding 5 — Libraries are already in good shape (58 monkeypatches across 16 packages)

Constructor injection works.  `chumicro_sockets.testing` (339 LOC), `chumicro_websockets.testing` (171 LOC), `chumicro_requests.testing` (180 LOC), `chumicro_wifi.testing` (188 LOC) — used heavily, no friction.  Five libraries have no `testing.py` (`compat`, `config`, `http_server`, `msgpack`, `ntp`) but four of those are stateless enough not to need one.  The one exception is `http_server`, where `_FakeListener` at `libraries/http_server/tests/test_http_server.py:34-50` (53 LOC) plus `_request_bytes()` at line 53-64 are inlined and should move to `chumicro_http_server.testing`.

The repeated pattern across runner-shaped libraries (`requests`, `mqtt`, `http_server`, `websockets`) is the tick-loop:

```python
for _ in range(200):
    if client.check(ticks.ticks_ms()): client.handle(ticks.ticks_ms())
    ticks.advance(1)
    if done_condition: break
```

Reinvented in `requests/test_requests.py:78-86`, `mqtt/test_client.py:38-43`, `http_server/test_http_server.py:88-95`, `websockets/test_client.py`.  A `RunnerHarness` in `chumicro_runner.testing` (30 LOC) collapses it everywhere.

### Finding 6 — No shared `support/` test-helpers package (deliberate)

Open question raised during the audit: should cross-cutting helpers (generic `fake_subprocess_runner`, `seed_tmp_workspace`) move to a `support/test_helpers/` package?  **No.**  When a library is copied into the [workspace-template](https://github.com/ChuMicro/ChuMicro-Workspace-Template) starter repo, anything under `support/` does not come with it.  Accept per-package duplication of test helpers.  If a pattern becomes load-bearing across 3+ packages, the path is to publish it as a real PyPI dependency, not to add an internal-only `support/` module.

Consistent with [Decision 0010](../decisions/0010-library-testability.md)'s "fakes co-located with the production code they fake" framing.

## Phases

Five phases, sequenced by ROI per phase (biggest workbench wins first, libraries-side polish last).  Each phase ships as one commit on `main` with VERSION bump on every affected package.

### Phase 1 — `workbench/workspace/src/chumicro_workspace/testing.py` (highest ROI)

Create the missing module.  Park:

- `FakePort(device, description)` — pyserial list_ports shim.
- `FakeSubprocessRunner` — callable that records `(args, kwargs)` and returns `CompletedProcess`.  Replaces 8+ inlined `fake_run` lambdas.
- `FakeProbeResult` — replaces `_Info` / `_MockEntry` inlines.
- `seed_workspace(tmp_path, **overrides)` — replaces 410 `_seed_workspace` call sites.
- `seed_project(tmp_path, **overrides)` — same for project scaffold.

Adopt across `workbench/workspace/tests/`.  Bump `chumicro-workspace` VERSION (minor — new public test-helper surface).  Estimated reclamation: ~800–1,200 test LOC.

### Phase 2 — `workbench/pytest-device/src/chumicro_pytest_device/testing.py`

Create the missing module.  Park:

- `FakePrepareItem`, `FakeRunFileItem`, `FakeTestItem` — pytest-item builders.
- `make_test_item(name, **overrides)` — factory.
- `FakeDiagnosticSession` — replaces inline `_stub_session`.
- `stub_config(**overrides)` — replaces `_stub_config`.

Adopt across `workbench/pytest-device/tests/`.  Bump `chumicro-pytest-device` VERSION.  Estimated reclamation: ~300–500 test LOC.

### Phase 3 — Production-code injection refactor (largest monkeypatch reduction)

Convert `monkeypatch.setattr` targets to constructor-injected callables on production code:

- `Deployer.subprocess_runner: Callable[..., CompletedProcess] | None = None` — defaults to `subprocess.run`.  Removes 15+ patches.
- `Deployer.drive_scanner: Callable[[], list[Path]] | None = None` — defaults to `_circuitpy_volume_candidates`.  Removes 13 patches.  Already fake-exposed in `chumicro_deploy.testing.isolate_from_host_filesystem`; the missing piece is production-code accepting the injection.
- `CLI.flash_firmware_fn` — same shape, removes 4 patches.
- `OnboardingConfig.uf2_search_paths: tuple[Path, ...]` — move module-level `_UF2_MOUNT_SEARCH_PATHS` constant to an injectable config dataclass.  Removes 22 patches.

Each lands as its own commit with VERSION bump on the touched workbench package.  Estimated monkeypatch reduction: ~250–350 (one-third of total).

### Phase 4 — `RunnerHarness` in `libraries/runner/src/chumicro_runner/testing.py`

Add a 30-LOC helper:

```python
class RunnerHarness:
    def __init__(self, system_under_test, ticks=None):
        self.system = system_under_test
        self.ticks = ticks or FakeTicks()
    def tick_until(self, predicate, max_ticks=200, advance_ms=1):
        for _ in range(max_ticks):
            if self.system.check(self.ticks.ticks_ms()):
                self.system.handle(self.ticks.ticks_ms())
            if predicate(): return
            self.ticks.advance(advance_ms)
        raise AssertionError(f"predicate not met after {max_ticks} ticks")
```

Adopt across `requests`, `mqtt`, `http_server`, `websockets` tests.  Estimated reclamation: ~150 test LOC.  Cross-runtime safe: `testing.py` declares `__chumicro_runtimes__ = ("cpython",)`.

### Phase 5 — `libraries/http_server/src/chumicro_http_server/testing.py`

Create the missing module.  Park `FakeListener` + `request_bytes()` builder from `tests/test_http_server.py:34-64`.  Adopt across http_server tests.  Estimated reclamation: ~100 test LOC.

The other four libraries without `testing.py` (`compat`, `config`, `msgpack`, `ntp`) stay as-is — their tests don't show inlined-fake bloat, and adding empty modules just to be uniform is shape-following without payoff.

## Totals

- Test LOC reduction: ~1,600–2,150 (~3 % of the 64,000-LOC test base, ~5 % of workbench).
- Monkeypatch reduction: ~250–350 calls (~40 % of workbench's 755, ~30 % of total).
- New `testing.py` modules: 3 (workspace, pytest-device, http_server).
- Production-code refactor surface: 4 injection seams across `chumicro-deploy` (Deployer + CLI + onboarding).

Not a wall-time speedup — pytest collection time is not load-bearing on preflight.  This is a maintainability win measured in dev-hours and a regression-shield win measured in fewer host-state-leak bugs of the kind the 2026-05-12 preflight investigation found.
