# Workstream: on-device functional tests dogfood `chumicro_config.load_runtime_config()`

Status: **proposed.**  Foundation (Decision 0056 — `transport.stage(extra_files=...)` API) shipped 2026-05-04; conftest + plugin + on-device test migration is the next session's lift.

(Originally filed as Phase 4.5b of the [`scripts-workbench-config-unification`](archive/scripts-workbench-config-unification.md) workstream; promoted to peer status 2026-05-05 once the parent closed and the upstream config-shape questions — Decision 0057 (two-file collapse) and `setup-schema-reconciliation` Strategy B — landed.)

## Premise

Decision 0055 (config pipeline unification) shipped half the dogfooding goal: every networking-library functional-test conftest now reads `workspace.yml` + per-project `config.toml` via `chumicro_workspace.compose_runtime_config()`, replacing the legacy `tomllib.load(chumicro-dev-config.toml)` pattern.  Decision 0057 subsequently collapsed the input layers from three files to two; `compose_runtime_config()` returns a plain `dict` ready for msgpack-encoding.

The other half — having on-device test code call `chumicro_config.load_runtime_config()` instead of importing `_test_creds` — needs to land too.  That's the migration this workstream covers.

The transport-API foundation already shipped (Decision 0056): `transport.stage()` accepts `extra_files: dict[str, bytes]` keyed by absolute device paths, so pytest-device can stage `runtime_config.msgpack` onto the device alongside library + harness + test sources.  Per-mode semantics: CP RAM raises `UnsupportedExtraFilesError`; CP flash, MP copy, and MP mount all write the bytes through their existing staging tree.  Host-side unit coverage at [`workbench/deploy/tests/test_extra_files_staging.py`](../../workbench/deploy/tests/test_extra_files_staging.py); no end-to-end functional test yet — see Pre-condition 3.

## Pre-conditions for the new session

A fresh agent picking this up cold should:

1. Read this file end to end.
2. Read [Decision 0055](../decisions/0055-config-pipeline-unification.md) (the unification target this work consumes), [Decision 0056](../decisions/0056-transport-extra-files-staging.md) (the transport-API foundation — what each mode raises / writes), and [Decision 0057](../decisions/0057-two-file-config.md) (the current 2-file input shape).
3. Hardware-validate the transport-API foundation end-to-end on the four-board canonical matrix *before* touching any conftest.  Stage a known-good `runtime_config.msgpack`, boot, read it back via `load_runtime_config()`, assert the dict round-trips byte-for-byte.  No such functional test exists today — the existing coverage is unit-only against `FakeTransport`.  This is the first deliverable of Step 1 below.
4. Audit every conftest in the repo (find under `libraries/`, `workbench/`, `support/`) for `_test_creds.py` materialisation or other static-secrets shims beyond the seven networking libraries.  The seven listed in Step 2 are the known set; confirm or extend.
5. **Boards required.**  Hardware-in-the-loop validation is mandatory; CPython unit tests can't catch the failure modes.  The four-board matrix is `pi-pico-w-circuitpython-board`, `pi-pico-w-micropython-board`, `lolin-s2-circuitpython-board`, `lolin-s2-micropython-board` (one of each runtime × two RP2040/ESP32 boards).

## Scope (sequenced)

The plugin's hook design depends on consumer behaviour — five of seven conftests just need static credentials staged, but three (mqtt, sockets, websockets) mutate the config dict mid-session with dynamic broker/echo/server values that aren't known until session-scoped fixtures spin up.  Designing the hook against `FakeTransport` alone risks getting late-binding wrong; designing it with one real consumer pins the contract.  Hence the sequencing below: plugin design + simplest consumer first, mechanical migration of the rest after.

### Step 1 — Plugin-side wiring + first consumer (wifi)

`workbench/pytest-device/src/chumicro_pytest_device/`:

1. `_test_runner.py` — retire `_KNOWN_TEST_SIBLING_MODULES = ("_test_creds.py",)` and `resolve_test_sibling_modules`.  Sibling-file staging becomes explicit (the conftest tells pytest-device what to stage) instead of name-pattern-based.
2. `plugin.py` — add a hook for conftests to register binary files.  Open API question to resolve in this session: `pytest_configure`-time set vs. session-scoped fixture vs. lazy callable that pytest-device invokes after fixtures resolve.  The hook *must* support late-binding so dynamic config (mqtt broker port, sockets echo port, ws server port) can land in the dict after the fixtures producing those values have run.  Recommended starting point: a session-scoped pytest fixture (`runtime_config_extras`) that other fixtures depend on; pytest-device reads it during stage prep.
3. Thread the captured dict through `transport.stage(extra_files={"/runtime_config.msgpack": <msgpack-encoded bytes>})` (path pinned by Decision 0035 §8).
4. Host-side unit tests for the new hook against `FakeTransport`'s `staged_extra_files`.

`libraries/wifi/functional_tests/`:

5. `conftest.py` — drop `_test_creds.py` materialisation; encode the merged config dict from `compose_runtime_config()` to msgpack via the new plugin hook.
6. `test_real_*.py` — replace the `_test_creds` import block with `chumicro_config.load_runtime_config()` (see template under Step 3).

7. **Hardware-validate on all four boards** (this also closes pre-condition 3).  Bring up a known config, stage it, boot, assert `load_runtime_config()` returns the same dict that `compose_runtime_config()` produced on the host.  CP-RAM-mode skip path verified to surface a clean error rather than a cryptic transport exception.

Step 1 is the API-design + risk-reduction slice.  Don't proceed to Step 2 until the four-board matrix is green.

### Step 2 — Mechanical migration of the remaining six conftests

`libraries/{requests,http_server,mqtt,sockets,websockets,ntp}/functional_tests/conftest.py`:

1. Drop the `_test_creds.py` materialisation.
2. Encode the merged config dict to msgpack via the plugin hook from Step 1.
3. Library-specific extras (mqtt broker spawn, sockets UDP echo, websockets PyPI server) mutate the merged dict with dynamic values *before* the hook captures it.
4. Requests conftest writes `NOW_UTC_TUPLE` (a tuple, not a string).  Pick a config-section home — recommend `requests.now_utc_tuple` so it lives alongside the other requests-section config — and bake it into the dict shape at generation time.

### Step 3 — On-device test rewrites

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

becomes:

```python
try:
    from chumicro_config import load_runtime_config
    from chumicro_config.section import InvalidConfigType
    _config = load_runtime_config()
    SSID = _config["wifi"]["ssid"]
    PASSWORD = _config["wifi"]["password"]
    _HAS_CREDS = True
except (OSError, InvalidConfigType):
    SSID = ""
    PASSWORD = ""
    _HAS_CREDS = False
```

`OSError` covers missing / unreadable file (`open()` at [runtime.py:40](../../libraries/config/src/chumicro_config/runtime.py:40)); `InvalidConfigType` covers a malformed payload (`load_runtime_config()` raises it from `chumicro_config.section` when the msgpack root isn't a dict).  `KeyError` from `_config["wifi"]["ssid"]` is the *next-line* concern, not the import block — handle it with per-test-file logic if a test legitimately wants to skip on missing keys vs. fail loudly on missing config file.

Library-specific extras (`BROKER_HOST` / `BROKER_PORT` / `ECHO_HOST` / `ECHO_PORT` / `WS_SERVER_HOST` / `WS_SERVER_PORT`, plus requests' `NOW_UTC_TUPLE`) read from their own sections of the runtime-config dict.

### Step 4 — Cleanup

* `**/_test_creds.py` gitignore line in mono-repo and workspace-template repo — remove (no more shim file).
* `_KNOWN_TEST_SIBLING_MODULES` removed from `_test_runner.py` (already done in Step 1).
* `resolve_test_sibling_modules` retired (already done in Step 1).
* `chumicro-pytest-device` VERSION minor bump — the conftest-to-plugin hook is a public-API surface change (Decision 0023 contract).
* Doc updates: `docs/contributing/device-testing.md` (the `_test_creds.py` pattern is described there), `docs/contributing/style-guide.md` if it mentions the pattern, plus library-level READMEs that reference the shim.

## Failure modes to watch for during hardware validation

1. **CP RAM mode + functional tests with config requirements.**  CP RAM mode raises `UnsupportedExtraFilesError` for `extra_files` (no filesystem to write to).  Functional tests that grow a config dependency must run on flash.  Surface this as an early `pytest.skip` or a clear error message — not a cryptic transport-level exception during staging.
2. **CIRCUITPY drive auto-reset on host write.**  Some CP firmware triggers a soft reset when the host writes to the drive while the device is running.  This may break the test mid-stage.  If it happens: bracket the `extra_files` write inside the existing flash-mode "soft reset before stage" window, or stage `runtime_config.msgpack` as the *first* file written (so the reset settles before test source lands).
3. **MP mount mode subtlety.**  `mpremote mount_local` mounts a host directory; writes to that directory are visible to the device immediately, but the device's `os.listdir` may cache.  Verify `chumicro_config.load_runtime_config()` reads succeed first time on a freshly-staged msgpack.
4. **Concurrent-broker dynamic config.**  MQTT's conftest spawns a host Mosquitto broker on a random port — the broker host/port can't be known until session-scoped fixtures resolve.  The plugin hook must capture the dict *after* fixtures run, not at `pytest_configure` time.  Verify the dynamic-broker path hardware-validates cleanly.
5. **`load_runtime_config` ABI compatibility.**  Decision 0035 §8 pins the on-device path to `/runtime_config.msgpack`.  Any drift between what the conftest writes and what `chumicro_config` reads breaks every functional test silently.  The Step 1 round-trip test covers this.
6. **Runtime config dataclass round-trip.**  Some libraries (wifi, mqtt) ship typed `from_dict()` factories that expect specific dict shapes.  Verify msgpack-encoded dicts round-trip through the library's `from_dict()` method on all four boards — bytes-equal is necessary but not sufficient if a library coerces types on the way in.

## Estimated scope

* ~15 files touched (7 conftests + 7 test files + plugin + _test_runner + plugin tests + docs).
* ~500 LOC delta net (much of it deletions — conftests get smaller; on-device test reads grow).
* 2–3 hours focused work plus hardware validation across the 4-board matrix.  Step 1 (plugin design + wifi) is the bulk of the design risk; Steps 2–4 are mechanical.

## Constraints

* The four-board matrix must pass functional tests after the migration.  Single-board passes are necessary but not sufficient — CP and MP report different config-load failure modes (CP raises `OSError`, MP raises `OSError` with different errno strings, etc.).
* No backwards-compat burden — `_test_creds.py` materialisation is deleted, not deprecated.  Old conftests don't need to keep working alongside new ones; the hook contract is hard-cutover.
* No on-device behaviour change to the libraries themselves; only test code rewrites.
* `chumicro-pytest-device` is the only workbench package with a public-API surface change — minor VERSION bump per Decision 0023.

## What this unblocks

After this workstream closes, the unification is end-to-end complete:

* Mono-repo's functional tests use the same `chumicro_config.load_runtime_config()` API user projects use.  No code path remains where the mono-repo reads config differently from a workspace-template-derived workspace.
* Future libraries that grow `from_dict` factories don't need a parallel "test creds shim" pattern — they read from `runtime_config.msgpack` directly, both in user code and in functional tests.
