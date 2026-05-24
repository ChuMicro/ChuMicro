# Decision 0056: `transport.stage()` accepts `extra_files: dict[str, bytes]` for binary file staging

Status: `accepted`
Date: `2026-05-04`
Summary: `TransportProtocol.stage()` adds `extra_files: dict[str, bytes]` for binary file staging; CP RAM mode raises `UnsupportedExtraFilesError`; other modes write bytes to the device path.
Related: Decision 0035 (runtime-config structure — `/runtime_config.msgpack` is the canonical on-device path), Decision 0036 (`chumicro-config` library — `load_runtime_config` reads from that path), Decision 0044 (deploy-time runtime-file filtering — host-side filter applied uniformly), Decision 0047 (`deploy_mode: flash` default — flash is the production-shaped path), Decision 0055 (config pipeline unification — `workspace.yml` + per-project `config.toml` flow into `runtime_config.msgpack` at deploy time), Decision 0057 (two-file config — collapsed Decision 0055's input layers from three files to two; this transport-API decision is unaffected).

## Context

`Deployer.deploy(source)` already supports binary file staging via `FileSource.files() -> dict[str, bytes]`.  `WithRuntimeConfig` rides that path: it generates `runtime_config.msgpack` and merges it into the file map at `/runtime_config.msgpack` so on-device code can call `chumicro_config.load_runtime_config()`.

`chumicro-pytest-device` uses the parallel `transport.stage(source_dirs, test_files, harness_source, *, extra_modules)` path.  `extra_modules` reads each path as UTF-8 source and registers it as an importable Python module (CP RAM mode inlines the source string into the bootstrap; CP flash and MP modes copy the `.py` file to the device).  This is how `_test_creds.py` gets staged.

Decision 0055 §4 retired `chumicro-dev-config.toml` and migrated functional-test conftests to read from the unified config sources (`workspace.yml` + per-project `config.toml` via `compose_runtime_config()`; Decision 0057 subsequently collapsed the input layers to these two files).  Half the dogfooding shipped: host-side data flow.  The other half — on-device test code calling `chumicro_config.load_runtime_config()` directly instead of importing `_test_creds` — was deferred because it requires staging a binary file (`/runtime_config.msgpack`) onto the device, and `transport.stage()` only supported text.

## Decision

`TransportProtocol.stage()` gains an `extra_files: dict[str, bytes] | None = None` keyword argument.  When provided, each `(device_path, content_bytes)` pair lands at `<device>:<device_path>` alongside library + harness + test sources.

Per-transport semantics:

* **CircuitPython, flash mode (`deploy_mode: flash`)** — host writes each `device_path` to the CIRCUITPY drive (host has read-write access while the device is USB-connected; the device sees the file when it next reads the filesystem).  Same path the existing flash deploy uses; one extra `Path.write_bytes` per file.
* **CircuitPython, RAM mode (`deploy_mode: ram`)** — raises `UnsupportedExtraFilesError` when `extra_files` is non-empty.  RAM mode bypasses the filesystem entirely (inline `exec()` strings via raw REPL).  A test that needs a runtime-config file must run on flash.  Decision 0047 already defaults to flash; this constraint reinforces that defaults bias.
* **MicroPython, copy mode (`deploy_mode: flash`)** — `mpremote fs cp` writes each file to the device root.  Same mechanism the existing `extra_modules` flash path uses, generalised to bytes.
* **MicroPython, mount mode (`deploy_mode: ram`)** — writes each file into the host directory `mpremote mount_local` mounts as the device filesystem.  No reset / no transport interaction; the device sees the file on next read.
* **`FakeTransport`** — stores in a `staged_extra_files: dict[str, bytes]` attribute for test inspection.  Mirrors the existing `staged_sources` accessor.

Naming locked to `extra_files` rather than `extra_binaries` / `extra_resources` / `extra_data`: the keys are device-side paths (already implies "file"); the value type (`bytes`) implies "anything that's not a Python module".  Existing `extra_modules` covers `.py` siblings; `extra_files` covers everything else.  The two parameters can be combined in one `stage()` call.

## Consequences

**Positive:**

* `chumicro-pytest-device` can stage `runtime_config.msgpack` alongside test files, completing the dogfooding gap from Decision 0055 §4.  On-device test code drops `from _test_creds import SSID, PASSWORD` in favor of `from chumicro_config import load_runtime_config; config = load_runtime_config()` — same surface user code uses.
* `transport.stage()` now matches `Deployer.deploy()` in expressivity for the binary-staging case.  Future workbench tools that need to stage non-Python artifacts (LittleFS images, calibration tables, pre-baked bytecode) ride the same hook.
* The `_KNOWN_TEST_SIBLING_MODULES = ("_test_creds.py",)` heuristic in `chumicro_pytest_device._test_runner` retires.  Sibling-file staging becomes explicit (the conftest tells pytest-device what to stage) instead of name-pattern-based.

**Negative:**

* Three transport implementations + `FakeTransport` need new code (~50–80 LOC each, plus tests).  The mode matrix (CP-RAM / CP-flash / MP-mount / MP-copy) gives four meaningfully different code paths.  CP-RAM raising `UnsupportedExtraFilesError` is the easy case; the others write bytes.
* RAM-mode tests that want runtime-config can no longer stay in RAM mode — they must move to flash.  This is consistent with Decision 0047's framing (RAM mode is for unit-style tests that don't need persistence) but is a behavioral change for any test currently running on RAM that grows a config dependency in Phase 4.5b's conftest-migration session.
* The on-device migration (deleting `_test_creds.py` materialization, rewriting test files to call `load_runtime_config`) is scoped separately and gated on this ADR + transport extension shipping first.

**Neutral:**

* Existing callers passing only `extra_modules` are unaffected — `extra_files` defaults to `None`.

## Out of scope

* The migration of conftests + on-device test code from `_test_creds.py` → `runtime_config.msgpack` + `load_runtime_config()` lives in a separate session (workstream detail in `plans/workstreams/on-device-config-dogfooding.md`).  This ADR ships the transport API extension + unit tests + `FakeTransport` extension; the on-device migration consumes it.
* `extra_files` content-type negotiation (msgpack vs JSON vs raw bytes) — out of scope; the parameter is type-agnostic, callers decide how to encode.
* Cross-transport file mode (`0o644` vs `0o755`) — every host-staged file lands with the host's default permissions; the device's filesystem semantics dictate what's reachable.  No CP / MP transport currently reads file permissions.
