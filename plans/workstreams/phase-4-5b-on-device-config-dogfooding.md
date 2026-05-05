# Workstream: Phase 4.5b — on-device functional tests dogfood `chumicro_config.load_runtime_config()`

Status: **proposed.**  Foundation (transport `extra_files` API) shipped 2026-05-04; conftest + on-device test migration is the next session's lift.

## Premise

Decision 0055 (config pipeline unification) shipped half the dogfooding goal: every networking-library functional-test conftest now reads `workspace.yml` + per-library `config.toml` + `secrets.yml` via `chumicro_workspace.compose_runtime_config()`, replacing the legacy `tomllib.load(chumicro-dev-config.toml)` pattern.

The other half — having on-device test code call `chumicro_config.load_runtime_config()` instead of importing `_test_creds` — needs to land too.  That's the migration this workstream covers.

The transport-API foundation already shipped: `transport.stage()` now accepts `extra_files: dict[str, bytes]`, so pytest-device can stage `runtime_config.msgpack` onto the device alongside library + harness + test sources.

## Pre-conditions for the new session

A fresh agent picking this up cold should:

1. Read this file end to end.
2. Read [Decision 0055](../decisions/0055-config-pipeline-unification.md) — defines the unification target this work consumes.  The transport hook (`transport.stage(..., extra_files=...)`) is plain implementation; check `workbench/deploy/src/chumicro_deploy/transport/` and its tests for the current API.
3. Read [`plans/workstreams/scripts-workbench-config-unification.md`](scripts-workbench-config-unification.md) for the broader workstream context (this is a deferred sub-phase of that workstream).
4. Verify `transport.stage(..., extra_files=...)` works on the four-board canonical matrix before starting any conftest migration — the foundation should be hardware-validated first.
5. **Boards required.**  Hardware-in-the-loop validation is mandatory; CPython unit tests can't catch the failure modes.  The four-board matrix is `pi-pico-w-circuitpython-board`, `pi-pico-w-micropython-board`, `lolin-s2-circuitpython-board`, `lolin-s2-micropython-board` (one of each runtime × two RP2040/ESP32 boards).

## Scope

### Per-conftest changes (7 files)

`libraries/{wifi,requests,http_server,mqtt,sockets,websockets,ntp}/functional_tests/conftest.py`:

1. Drop the `_test_creds.py` materialisation (lines that write `SSID = ...` / `PASSWORD = ...` / `BROKER_HOST = ...` / etc.).
2. Replace with: encode the merged config dict to msgpack, write to a sibling `_runtime_config.msgpack` (or pass directly to pytest-device via a new fixture / config hook).
3. Library-specific extras (mqtt broker spawn, sockets UDP echo, websockets PyPI server) mutate the merged dict with dynamic values *before* msgpack-encoding.

### Pytest-device wiring (1 file + tests)

`workbench/pytest-device/src/chumicro_pytest_device/`:

1. `_test_runner.py` — retire `_KNOWN_TEST_SIBLING_MODULES = ("_test_creds.py",)`.  Replace with explicit handoff: the conftest tells the plugin what binary files to stage (e.g. `_runtime_config.msgpack` sibling auto-pickup, or a `chumicro_pytest_device.stage_extra_file(name, content)` API the conftest calls in `pytest_configure`).
2. `plugin.py` — when staging a test file, collect any `_runtime_config.msgpack` siblings + thread them through `transport.stage(extra_files={"/runtime_config.msgpack": <bytes>})`.
3. Tests for the new sibling-pickup path.

### On-device test rewrites (7+ files)

Every `libraries/*/functional_tests/test_real_*.py` that does:

```python
try:
    from _test_creds import SSID, PASSWORD
    _HAS_CREDS = True
except ImportError:
    SSID = ""
    PASSWORD = ""
    _HAS_CREDS = False
```

Becomes:

```python
try:
    from chumicro_config import load_runtime_config
    _config = load_runtime_config()
    SSID = _config["wifi"]["ssid"]
    PASSWORD = _config["wifi"]["password"]
    _HAS_CREDS = True
except (OSError, KeyError):
    SSID = ""
    PASSWORD = ""
    _HAS_CREDS = False
```

(The exact exception list depends on what `load_runtime_config` raises when the msgpack file is missing — needs verification.)

Library-specific extras (`BROKER_HOST` / `BROKER_PORT` / `ECHO_HOST` / `ECHO_PORT` / `WS_SERVER_HOST` / `WS_SERVER_PORT`) read from their own sections of the runtime-config dict.

### Cleanup

* `**/_test_creds.py` gitignore line in mono-repo and template repo — remove (no more shim file).
* `_KNOWN_TEST_SIBLING_MODULES` removed from `_test_runner.py`.
* `resolve_test_sibling_modules` retired or repurposed.
* Doc updates: `docs/contributing/device-testing.md`, `style-guide.md` if it mentions the pattern.

## Failure modes to watch for during hardware validation

1. **CP RAM mode + functional tests with config requirements.**  CP RAM mode raises `UnsupportedExtraFilesError` for `extra_files` (no filesystem to write to).  Functional tests that grow a config dependency must run on flash.  Surface this as an early `pytest.skip` or a clear error message — not a cryptic transport-level exception during staging.
2. **CIRCUITPY drive auto-reset on host write.**  Some CP firmware triggers a soft reset when the host writes to the drive while the device is running.  This may break the test mid-stage.  If it happens: bracket the `extra_files` write inside the existing flash-mode "soft reset before stage" window, or stage `runtime_config.msgpack` as the *first* file written (so the reset settles before test source lands).
3. **MP mount mode subtlety.**  `mpremote mount_local` mounts a host directory; writes to that directory are visible to the device immediately, but the device's `os.listdir` may cache.  Verify `chumicro_config.load_runtime_config()` reads succeed first time on a freshly-staged msgpack.
4. **Concurrent-broker dynamic config.**  MQTT's conftest spawns a host Mosquitto broker on a random port — the broker host/port can't be known until `pytest_configure` runs.  The conftest must mutate the merged config dict + re-encode the msgpack each session.  Verify the dynamic-broker path hardware-validates cleanly (the legacy `_test_creds.py` rendering didn't have this complexity since it was always written fresh).
5. **`load_runtime_config` ABI compatibility.**  Decision 0035 §8 pins the on-device path to `/runtime_config.msgpack`.  Any drift between what the conftest writes and what `chumicro_config` reads breaks every functional test silently.  Add an integration test that round-trips a known config dict through the full pipeline.

## Estimated scope

* ~15 files touched (7 conftests + 7 test files + plugin + _test_runner + tests + docs).
* ~500 LOC delta net (much of it deletions — conftests get smaller; on-device test reads grow).
* 2-3 hours focused work plus hardware validation across the 4-board matrix.

## Constraints

* The four-board matrix must pass functional tests after the migration.  Single-board passes are necessary but not sufficient — CP and MP report different config-load failure modes (CP raises `OSError`, MP raises `OSError` with different errno strings, etc.).
* No backwards-compat burden — pre-Phase-4.5a `_test_creds.py` materialisation deleted, not deprecated.
* No on-device behaviour change to the libraries themselves; only test code rewrites.

## What this unblocks

After this workstream closes, the unification is end-to-end complete:

* Mono-repo's functional tests use the same `chumicro_config.load_runtime_config()` API user projects use.  No code path remains where the mono-repo reads config differently from a workspace-template-derived workspace.
* Phase 4.5a (the `!secret` simplification call) becomes a clean follow-up — the marker resolution is a workspace-pipeline concern, separate from the on-device read path.
* Future libraries that grow `from_dict` factories don't need a parallel "test creds shim" pattern — they read from `runtime_config.msgpack` directly, both in user code and in functional tests.
