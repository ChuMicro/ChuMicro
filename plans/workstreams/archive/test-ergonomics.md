# Workstream: Test Ecosystem Ergonomics

Status: **closed** — audited 2026-05-12, Phases 1-3+5+6 shipped 2026-05-12; Phase 4 declined after deeper inspection.  Commits: `115510e6` (1), `b472f976` (2), `6d66ae1c` + `6111acd0` (3), `6256ce90` (5), `8f7d7f79` + `0afa7f4c` + `98cd48df` + `5dbad647` (6).

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

Consistent with [Decision 0010](../../decisions/0010-library-testability.md)'s "fakes co-located with the production code they fake" framing.

## Phases

Five phases, sequenced by ROI per phase (biggest workbench wins first, libraries-side polish last).  Each phase ships as one commit on `main` with VERSION bump on every affected package.

### Phase 1 — `workbench/workspace/src/chumicro_workspace/testing.py` (shipped 2026-05-12)

Public module created at `workbench/workspace/src/chumicro_workspace/testing.py` exporting:

- `seed_workspace(tmp_path, *, runtime, device_id)` — collapses the old `_seed_workspace` + `_seed_workspace_with_cp_device` into one parameterized helper.
- `seed_project(workspace_root, name)` — projects/<name>/{project_config.toml,code.py,main.py} scaffold.
- `FakePort(device, description)` — pyserial `ListPortInfo` shim.
- `FakeSubprocessRunner` + `FakeSubprocessCall` — callable recorder with `returncode` / `returncodes` knobs.
- `fake_probe_info(...) -> FakeProbeInfo` — matches `chumicro_deploy.probe_device`'s return shape with firmware-floor-passing defaults and a `with_implementation=False` branch for the no-marker path.

Adoption in `tests/test_cli.py`: 30+ `seed_workspace` sites, 33 `fake_probe_info` sites, 4 `FakePort` sites, 14 `FakeSubprocessRunner` sites; `_seed_workspace_with_cp_device` collapsed to a one-line wrapper.  In `tests/test_onboarding.py`: the `_info_with_implementation` / `_info_without_implementation` helpers become two-line wrappers around `fake_probe_info`.

Skipped on cost-benefit: `_patch_environment` in `test_cli.py` (already DRY across 5 callers via a parameterized `run_returncode`); `_install_capturing_subprocess` in `TestInstallLibraries` (already a class helper).  Migration would touch 30+ assertion lines for marginal LOC win.

Result: 740 test LOC removed, 218 LOC added in `testing.py`, net -168 LOC.  `chumicro_workspace.testing` at 98 % coverage from organic test usage.  `chumicro-workspace` VERSION 0.24.0 → 0.25.0 (minor, new public surface).  Full 756-test workspace suite passes.

The structural win is centralized fakes and a visible public surface for downstream workspace-template authors — LOC reduction is a side effect, not the headline.

### Phase 2 — `workbench/pytest-device/src/chumicro_pytest_device/testing.py` (shipped 2026-05-12)

Public module created at `workbench/pytest-device/src/chumicro_pytest_device/testing.py` exporting:

- `HotPathTransport` — focused FakeTransport for the plugin hot path (`connect` / `stage` / `execute` / `execute_scripts` / `recover` / `soft_reset` / `inline_script_budget_bytes` / `disconnect` with per-method raise hooks).
- `FakeConfig` — `pytest.Config` stand-in with `rootpath` + `stash` + `getoption`.
- `FakeSession` — `pytest.Session` stand-in carrying `_TransportCache` + `DeviceBackend` + `FakeConfig`.
- `hot_path_device(runtime)` — `DeviceEntry` builder with sensible defaults.
- `prime_transport_cache(cache, device, transport)` — install a pre-built transport bypassing `build_transport_for_entry`.
- `make_prepare_item` / `make_run_file_item` / `make_test_item` — pytest-item builders via `__new__` + attribute assignment (bypasses `Item.from_parent`'s parent-required brittleness in unit tests).

Adoption in `tests/test_plugin.py`: 15+ `HotPathTransport` sites, 15+ `hot_path_device` sites, 12+ `prime_transport_cache` sites, 18+ `make_*_item` sites, 3 `FakeSession` sites.

Skipped on scope: the two `_stub_config` inline class methods inside `TestPytestCollectionModifyItems` / `TestPytestCollectionModifyItemsFeatures`, and the `_stub_session` helper specific to feature-marker tests.  These are class-internal helpers tightly coupled to `runtime_config` plumbing — a future Phase 2.5 cleanup, not core Phase 2 scope.

Result: 159 test LOC removed, 261 LOC added in `testing.py`.  `chumicro_pytest_device.testing` at 86 % isolated coverage (matches `chumicro_deploy.testing`'s pattern — testing.py modules aren't gated by overall package coverage).  `chumicro-pytest-device` VERSION 0.8.0 → 0.9.0 (minor, new public surface).  Full 188-test pytest-device suite passes; ruff + chumicro-checks clean.

### Phase 3 — CLI env-dataclass injection seam (shipped 2026-05-12)

The workstream's original framing — "Deployer.subprocess_runner / drive_scanner / flash_firmware_fn + OnboardingConfig.uf2_search_paths" — assumed missing injection seams that mostly already exist (`detect_board_state` already accepts `uf2_search_paths` / `probe_function` / `drive_scanner`; `CircuitpythonTransport` already accepts `serial_port_factory` / `time`; there's no `Deployer` class to add fields to).  The actual gap was that tests reach production code via `cli.main([...])` end-to-end paths, and `argparse`-style dispatch can't easily thread kwargs.  Real monkeypatch site count: ~45, not 250-350.

Shipped shape:

- **`chumicro_workspace.cli.CliEnv`** (`6d66ae1c`, workspace 0.25.0 → 0.26.0) — frozen dataclass with `uf2_search_paths`, `subprocess_runner`, `flash_firmware_fn`.  `cli.main(argv, *, env=None)` stashes env on `args._env`; sub-commands read it.  Dropped 22 monkeypatches across 22 test sites — 5 `_UF2_MOUNT_SEARCH_PATHS`, 14 `cli.subprocess.run`, 3 `chumicro_deploy.flash_firmware`.  The `TestDoctorFixFskitWedge._patch_environment` helper now returns a `FakeSubprocessRunner` directly; `TestInstallLibraries._install_capturing_subprocess` deleted entirely (callers construct their own runner).  `_fix_fskit_wedge()` gains a `subprocess_runner` param so the CLI threads env through.

- **`chumicro_deploy.cli.CliEnv`** (`6111acd0`, deploy 0.16.0 → 0.17.0) — mirrors the workspace shape: `flash_firmware_fn`, same `main(argv, *, env=None)` + `args._env` pattern.  Dropped 4 monkeypatches on `chumicro_deploy.cli.flash_firmware`.

Drive-scanner injection deferred: the workstream framed it as "Deployer.drive_scanner" with 13 patches; only 1 direct `monkeypatch.setattr` site remained after Phase 1 + the existing `chumicro_deploy.testing.isolate_from_host_filesystem` adoption.  Not worth the API surface today.

Result: 26 monkeypatches dropped (~half of the realistic-scope target after recounting; 6× lower than the workstream's original 250-350 estimate).  Both CLIs gain a public, discoverable injection seam — a small step toward "explicit injection" over "monkeypatch on private module surface."  Full 752 workspace + 894 deploy tests pass.

### Phase 4 — `RunnerHarness` in `chumicro_runner.testing` (declined 2026-05-12)

Deeper inspection of the four target libraries showed the tick-loop shapes are **not uniform** enough for a single harness to be a clean win:

- **requests**: `drive_until_done(client, handle, ticks)` — needs `check()` + `handle()` + a `handle.done` flag.
- **mqtt**: `_drive(client, ticks, count=1)` — fixed-count iteration, no predicate.
- **http_server**: `_drive_until_idle(server, ticks)` — `handle()` + `in_flight == 0` predicate, no `check()`.
- **websockets**: `while` loops gated on state-machine fields (`_connecting_phase == SENDING_HANDSHAKE`, etc.), with manual handshake feeding via `_drive_handshake`.

A unified `RunnerHarness` accepting `check_fn` / `handle_fn` / `predicate` / `max_ticks` / `advance_ms` would be a configurable monster, and per-call-site usage gets **longer** because every call must pass lambdas for the three slots.  The current per-library helpers are 8-11 LOC each, used 5-20 times per library, and read naturally because they encode the library's specific concept (`handle.done`, `in_flight == 0`).  Forcing a shared shape would hurt readability for marginal LOC savings.

Per the project rule "Don't add features, refactor, or introduce abstractions beyond what the task requires": declined.  The per-library helpers stay.

### Phase 5 — `chumicro_http_server.testing` (shipped 2026-05-12)

Public module created at `libraries/http_server/src/chumicro_http_server/testing.py` exporting:

- `FakeListener(connections)` — listener stub that hands out queued sockets on `accept()`; empty queue raises `OSError(11, "would block")` so the server's EAGAIN path runs unchanged.
- `request_bytes(method, path, *, headers, body)` — HTTP/1.1 request byte-string builder; auto-prepends `Content-Length` when body is present.

Adoption: 48 reference sites across `tests/test_http_server.py` migrated from `_FakeListener` / `_request_bytes` to the new public names.  Module declares `__chumicro_runtimes__ = ("cpython",)`.  Local `_make_server`, `_drive_until_idle`, `_drive_until_all_responded` stay — they're shape-specific to the http_server test file and don't generalize.

Result: 32 test LOC removed, 71 LOC added in `testing.py`.  `chumicro_http_server.testing` at 100 % isolated coverage from organic test usage.  119 host-side + 654 MP unix-port + 654 CP unix-port tests pass.  `chumicro-http-server` VERSION 0.8.0 → 0.9.0 (minor, new public surface).

The other four libraries without `testing.py` (`compat`, `config`, `msgpack`, `ntp`) stay as-is — their tests don't show inlined-fake bloat, and adding empty modules just to be uniform is shape-following without payoff.

### Phase 6 — Transport / fake-class ergonomics (shipped 2026-05-12)

Triggered by a user-spotted finding: `~50 of the ~60 serial_port_factory= sites in test_circuitpython_transport.py wrap a FakeSerialPort in a 4-line closure that always returns the same instance the test already built` — the factory-callable contract was friction, not real variety.

- **`FakeSerialPort.__call__` → self** (`8f7d7f79`, deploy 0.17.0 → 0.18.0).  Added `__call__(self, *_args, **_kwargs)` to both `chumicro_deploy.testing.FakeSerialPort` and `chumicro_repl.testing.FakeSerialPort` so instances double as a `serial_port_factory` callable.  Activated the previously-dead `open_error=` kwarg so tests script "factory raises" without a custom closure.  Migrated 30 simple `def factory(**kwargs): return port` closures in test_circuitpython_transport.py + 16 `port_factory=lambda *_args, **_kwargs: port` lambdas in repl tests + dropped repl's `_build_factory` helper.  -148 LOC across test files.

- **`CircuitpythonTransport.drive_scanner` kwarg** (`0afa7f4c`, deploy 0.18.0 → 0.19.0).  Added `drive_scanner: Callable[[], list[Path]] | None = None` to the transport constructor, defaulting to `circuitpy_drive._circuitpy_volume_candidates`.  The two internal scan sites now route through `self._drive_scanner`.  Migrated the `_make_flash_transport` + `_connect` test helpers + 14 per-test sites via a regex-based bulk rewriter.  ~19 monkeypatches dropped.  4 monkeypatches stay legitimately: 3 tests exercise circuitpy_drive's module-level helpers directly (not transport-internal), and 2 auto-correct tests need the module-level patch because the auto-correct path goes through `find_circuitpy_drive_for_uid` — which calls the module-global, not the transport's scanner.

- **`recovery.diagnose_port_holders` runner= kwarg** (`98cd48df`, deploy 0.19.0 → 0.20.0).  Added `runner: Callable[..., subprocess.CompletedProcess] = subprocess.run` to `diagnose_port_holders` and `_full_command_for_pid`.  5 recovery test methods migrated from `monkeypatch.setattr(recovery.subprocess, "run", ...)` to `runner=fake_run` kwarg.

- **`chumicro_deploy.cli.CliEnv.probe_device_fn`** (`5dbad647`, deploy 0.20.0 → 0.21.0).  Added `probe_device_fn` to deploy's CliEnv.  2 test sites migrated from monkeypatch on `cli.probe_device` to `env=CliEnv(probe_device_fn=...)`.

Scope decisions:

- `subprocess_runner` threading through `flash_drive` was deferred: zero direct monkeypatches on `flash_drive.subprocess.run` across deploy tests — `chumicro_deploy.testing.isolate_from_host_filesystem` already absorbs every seam via a single autouse-friendly helper.  Adding `subprocess_runner` to 7 flash_drive functions + threading from `CircuitpythonTransport` would be wide surgery for zero monkeypatch reduction.
- Deploy CliEnv expansion with `subprocess_runner` / `drive_scanner` fields was declined: deploy CLI sub-commands don't directly call subprocess.run or scan drives.  The transport's `drive_scanner` kwarg (above) and recovery's `runner=` kwarg cover the actual leverage points.

Phase 6 totals: ~26 monkeypatches dropped, -148 LOC of factory wrappers, 1 new fake-class method (`__call__`), 1 new transport kwarg (`drive_scanner`), 2 new helper kwargs (`runner=` on recovery), 1 new CliEnv field (`probe_device_fn`).

## Totals (actuals, after Phase 6)

- Test LOC reduction: **~750 net** (Phases 1-5 saved ~600; Phase 6a alone removed 148 LOC of factory-closure wrappers).
- Monkeypatch reduction: **~90 calls** total (885 → 795; ~10 % of starting total).  Phase 6 added ~26 to the earlier 40-ish drop.
- New `testing.py` modules: **3** (workspace, pytest-device, http_server).
- New public CLI injection surface: **2** (`chumicro_workspace.cli.CliEnv`, `chumicro_deploy.cli.CliEnv`).
- New transport-level injection seams: **2** (`CircuitpythonTransport.drive_scanner`, `recovery.diagnose_port_holders(runner=...)`).
- New fake-class ergonomic surface: `FakeSerialPort.__call__` (deploy + repl) + `open_error=` kwarg.

Not a wall-time speedup — pytest collection time is not load-bearing on preflight.  The actual wins are:

- **Test infrastructure is now visible at each workbench package's public surface**, not buried inside test files.  Downstream `chumicro-workspace-template` authors who write workspace tests can `import` the helpers instead of inventing their own.
- **Two CLIs gained an explicit injection seam** (`cli.main(argv, *, env=...)`), so tests can swap callables without monkeypatching private module symbols.  Future seams add fields to `CliEnv` rather than scattering new monkeypatch sites.
- **Reduced regression risk** in the test base: the `isolate_from_host_filesystem`-style host-state-leak class of bugs is now harder to introduce because the seams are explicit.

Phase 4 declined: tick-loop shapes are too divergent across libraries to unify cleanly without hurting readability.
