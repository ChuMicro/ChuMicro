# Decision 0058: Test skips must be loud, never silent

Status: `accepted`
Date: `2026-05-07`
Summary: Test skips must use `chumicro_test_harness.skip(reason)`; CHU009 forbids bare-return skips, CHU010 forbids tests with no assertions; runtime/feature markers replace silent guards.
Related: Decision 0009 (testing strategy), Decision 0010 (constructor injection + per-library `testing.py`), Decision 0014 (runner-shaped functional contract), Decision 0027 (`devices.yml` schema), Decision 0036 (chumicro-config — runtime-config keys).

## Context

A multi-session audit of `libraries/*/tests/` and `libraries/*/functional_tests/` surfaced a systematic problem: every "real network" functional test opened with `if wifi_cfg is None: return` (and similar credential / capability guards), which the lightweight test runner reports as `PASS`.  A fresh-clone contributor with no `secrets.toml`, or a board running on the wrong hardware tier, would see "all green" without any of the wifi / sockets / mqtt / requests / ntp / http_server / websockets functional tests ever touching the network.

Three distinct silent-skip shapes were in active use:

* **Credential guards** — 13 tests each opening with `if wifi_cfg is None: return`.  The host plugin's `required_keys` mechanism already skips at collection time when keys are absent, so reaching the body means the conftest forgot to declare a required key — but the bare return fakes a PASS instead of surfacing the bug.
* **Per-board capability guards** — 16 tests with `if not _HAS_ESP32: return` / `if not _HAS_NETWORK: return` / `if not _IS_MICROPYTHON: return`.  Board feature gates that the runner has no visibility into.
* **Host-fixture guards** — 3 cases (UDP echo server, websocket server, Pi Pico W self-loopback) where the conftest registers `None` values for fixtures that didn't start, and `required_keys` (which checks key presence, not value sanity) lets the test run.

Beyond bare returns: 10 tests had **zero assertions** in their bodies — pure setup + side-effecting calls that could only fail by crashing.  Idempotency tests (`test_close_idempotent` etc.) relied implicitly on "if it doesn't raise, it works"; a regression that flipped behavior without raising would not fail them.

The conftests added a third silent-skip shape: `try: compose_runtime_config(...) except Exception: return None` collapsed "fresh-clone, never set up" and "user has a malformed `secrets.toml`" into the same outcome.  A real config bug silently skipped the whole session instead of surfacing the parse error.

Phases 1–7 of the silent-skip workstream eradicated all four shapes.  This ADR records the policy that emerged so the patterns can't quietly come back.

## Decision

**Test skips must be loud.**  Concretely:

1. **`chumicro_test_harness.skip(reason)` is the canonical skip primitive.**  It works under both the lightweight test_harness runner (cross-runtime, on-device) and pytest (host-side unit tests) — under pytest it raises `pytest.skip.Exception`; under the harness it raises a sentinel the runner catches and emits as `SKIP <name> (<reason>)`.  Tests **never** use bare `return` for a "this prerequisite isn't met" condition.

2. **Runtime-level filters declare `__chumicro_runtimes__`.**  A file that only makes sense on one runtime (CP NVM backend, MP NVS backend, MP `network` adapter) declares `__chumicro_runtimes__ = ("micropython",)` (or the appropriate set) at module level.  The deploy pipeline filters at collection time; wrong-runtime targets never see the file.

3. **Per-board feature filters declare `__chumicro_features__`.**  A file that needs a feature finer-grained than the runtime — currently just `("esp32",)` — declares it as a file-level marker.  The pytest-device plugin probes each target device once per session via the existing transport, deselects items whose target lacks a required feature, and runs the rest.  Devices without the feature get items deselected, not skipped — same effect as the runtime filter.

4. **Conftest `required_keys` handles missing runtime config.**  Each library's `functional_tests/conftest.py` declares the runtime-config keys its tests need via `set_runtime_config(..., required_keys=("wifi.ssid", ...))`.  When the merged config is `None` (fresh clone) or a key is absent, the host plugin applies a session-wide `pytest.mark.skip` with a clear "missing required runtime-config keys" message.  The conftest only suppresses the payload (returns `None`) for the **missing-file** case — any exception from `compose_runtime_config` propagates so a malformed `secrets.toml` is a loud collection-time error, not a silent skip.

5. **A test body that's reached past the collection-time gates must hard-fail on residual config bugs.**  When a credential guard fires inside a test body (the conftest's `required_keys` should have caught it), it's a conftest bug — the body raises `AssertionError` with a message naming the gate that was missed.  Hard fail at runtime is the right surface: the user sees that the conftest is incomplete, not a silent PASS.

6. **Every test must have at least one assertion.**  An `assert`, a `raise`, a `with raises(...)`, a call to `skip` / `fail` / `importorskip`, or an `AssertionError` — anything that gives the test a way to fail other than crashing.  Idempotency tests assert post-state (`assert sock.fileno() == -1` after a double-close, `assert handle.active is False` after a double-remove); the absence of an explicit assertion lets a behavior regression report as PASS.

The rules are enforced as durable lint:

* **CHU009** (in the [`chumicro-checks`](../../workbench/checks/) package) — forbids any `return`/`pass` that makes a `def test_*` PASS without asserting, in `libraries/*/{tests,functional_tests}/test_*.py`: a `return`/`pass` as the last statement of any `if` body (the guarded branch skips the assertions below it), and a bare early `return`/`pass` in the test body that orphans the assertions after it.  Returns inside a nested closure (factory, callback) are that callable's logic and are not flagged.  Per-line `# noqa: CHU009` for genuine exceptions.
* **CHU010** (same module) — forbids test functions with no assertion / raise / skip / fail call.  Per-line `# noqa: CHU010` for genuine exceptions.

## Rejected

**Pytest-side `pytest.mark.skipif` for credential guards.**  Rejected: device tests run via the pytest-device plugin's collection path, where a host-side decorator can't see whether a board has wifi credentials — that information lives in the staged runtime-config payload, available only to the device.  The `required_keys` mechanism is the layer that can answer the question, and it does so at collection time, not as a per-test marker.

**A per-device `features:` list in `devices.yml`.**  Rejected: maintaining a board → features map is exactly the kind of churn the user explicitly wanted to avoid ("we don't want to be in the business of maintaining boards here").  Probing the device directly via `transport.execute` is authoritative — the board reports its own capabilities — and costs ~1 short script per target device per session.

**A unified `chumicro_skip` library that wraps both pytest and the harness.**  Rejected: the test harness's `skip.py` already does this in 30 lines via runtime feature detection (alias `_SkipException` to `pytest.skip.Exception` when pytest is importable, fall back to a plain Exception subclass on the unix-ports).  Promoting it to a separate library would add a dependency without adding value.

**Soft-warning lint that emits a warning instead of failing.**  Rejected: silent-skip patterns crept back over time even when noticed during review.  A hard CI-failing lint with explicit `# noqa` suppression makes the rule visible at the diff level.

**Block CHU009 / CHU010 from workbench / support trees.**  Already done — the rules scope to `libraries/<name>/{tests,functional_tests}/`.  The workbench has its own silent-skip patterns (recovery-layer audit, separate workstream) and applying the same rules would generate a burst of false-positives on workbench tests that legitimately wrap external tooling.  Scope can expand later when the workbench audit lands.

## Consequences

- Functional test files that gate on per-board features declare `__chumicro_runtimes__` and/or `__chumicro_features__` at module level.  Wrong-runtime / wrong-feature targets never collect those items.
- The `chumicro_test_harness.skip` primitive becomes the only acceptable runtime skip mechanism in test bodies.  `chumicro_test_harness.runner.run_module` emits `SKIP <name> (<reason>)` lines that the result parser already understands; pytest reports its native `Skipped` outcome.
- `MQTTClient.from_config` (and any future `from_config` shape) refuses to construct without explicit required keys — a missing key raises `MissingConfigKey`, never falls back to a public-test endpoint.  Decision 0036's `load_section` / `try_load_section` distinction is the right shape; libraries that need a soft path use `try_load_section` and document the soft outcome.
- The pytest-device plugin probes each target device for features at the first feature-marked collection — cost is bounded (≤1 transport.execute per target per session), and absent / offline devices emit a warning + treat the device as featureless rather than crashing the session.
- New device libraries that introduce a feature beyond the current `("esp32",)` extend `KNOWN_FEATURES` + `FEATURE_PROBE_SCRIPT` + `parse_feature_probe_output` in `chumicro_pytest_device.features` together.  A test enforces that every `KNOWN_FEATURES` entry is mentioned in the probe script so a typo doesn't silently report the new feature as absent on every device.
- Conftests across `libraries/*/functional_tests/` no longer swallow `compose_runtime_config` exceptions.  Malformed `secrets.toml` is a pytest collection error with the original traceback; missing `secrets.toml` is the only silent path (the fresh-clone case).
- Every new test gets the CHU010 review at lint time.  Idempotency tests, smoke tests, and import-only tests need a positive post-state assertion (or `# noqa: CHU010` with a reason in the test docstring).  The lint catches regressions before they can land.
- The audit's spawned-task work (removing `MQTTClient.from_config`'s `test.mosquitto.org` fallback) and the `mqtt.broker.host` placeholder fix in the conftest are the production-side counterparts: the same "skips must be loud" principle applies to silent third-party connections in production code.
