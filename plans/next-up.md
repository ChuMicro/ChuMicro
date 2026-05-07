# Next Up

> **Agent-managed file.**  Cross-maintain with [`now.md`](now.md): the snapshot there mirrors whatever is `[ ]` in `## Now` here.  Each top-level bullet in this file is capped at 5 bullet points (lead + sub-bullets, CHU011) — anything that needs more lives in a workstream file under [`workstreams/`](workstreams/), surfaced from here as a one-line pointer.  When you check an item off, move it to `## Done (recent)` as a one-line pointer in the same edit (don't paste detail back).

## Now

_idle — pickup candidates live in `## Next`._

## Next

Independent items.  Most have either shipped phases (status in the linked workstream) or are unscoped placeholders waiting on a forcing function.

- [ ] **Library `from_config` factories — config-aware constructors across the six networking libs.**  Phase 0 shipped 2026-05-06 (mqtt / requests / http_server / ntp / websockets gained `[tool.chumicro.config]` blocks; sockets deliberately got no manifest).  Phases 1 (pytest-device validation hook) + 2 (per-lib `from_config` factories with hardware validation) + 3 (`scripts/run.py deploy-example`) remain.  Detail: [`workstreams/library-config-aware-refactor.md`](workstreams/library-config-aware-refactor.md).

- [ ] **Two-board client/server example** — captured 2026-05-06 during F5 boot-shim simplification.  Replace deprecated `examples/two_projects/` with two physical-board demo (one HTTP server + one client, or MQTT pub + sub).  Single-project shape per board; lives at `examples/two_board_handshake/{server,client}/`.  Hardware-validates two-board acceptance scenarios chumicro doesn't otherwise exercise.

- [ ] **Beginner-comfort onramp Phase 3+** — Phases 1 + 2 + audit-of-the-audit shipped 2026-05-02 (see `## Done`).  Phase 3+ unscoped; reopen when the next first-encounter friction surfaces from real users.  Detail: [`workstreams/beginner-onramp.md`](workstreams/beginner-onramp.md).

- [ ] **Scripts → workbench migration backlog** (Decision 0032 rule 8).  Phases 1–3 shipped 2026-04-27.  Smaller candidates remain: `scripts/generate_config_files.py` could thin-wrap `chumicro_workspace`; the rest of `scripts/{audit_gates,bundle_manager,docs_deploy,prepare_*,ide_sync,verify_examples,check_*}.py` reviewed 2026-04-27 and confirmed mono-repo CI plumbing — stays in `scripts/`.

- [ ] **`discover` interactive multi-board registration** — option (c) shipped 2026-04-26 (`add-device --address <port> <id>` auto-detects runtime).  Still deferred: (a) `add-device --auto` interactive port sweep, (b) `discover --register` doing the sweep as a side-effect.  Hold until a 5+-board user complains.

- [ ] **Expand the device test matrix beyond ESP32-S2** now that transport tooling is proven on both MicroPython and CircuitPython.

- [ ] **OTA (over-the-air updates)** — placeholder; trigger to revisit is a real thing on a wall / yard / inconvenient location that needs an update without physical access.  Detail: [`workstreams/ota.md`](workstreams/ota.md).

- [ ] **CHU006 README + docs scan extension** — captured 2026-05-06 during the publishable-isolation audit.  Extend `check_no_repo_refs.py`'s `_scan_roots()` from `*/src/` to also walk `libraries/<name>/README.md`, `workbench/<name>/README.md`, `support/test_harness/README.md`, and per-library `docs/`.  Lint extension is ~5 lines + `_SKIPPED_ROOTS` placeholder; cleanup of the ~80 leaking lines across ~20 files is half-day.

- [ ] **CHU008 — workspace-template repo isolation lint, distributed via `chumicro-workspace`** — captured 2026-05-06.  Template repo's leak shape is mono-repo-shape prose framing the user's workspace as an upstream derivative.  Cannot live in mono-repo `scripts/`; right home is a `chumicro-workspace check-isolation` subcommand.  Same machinery as CHU006, different forbidden-pattern set.  Holds on the CHU-rules-home decision below.

- [ ] **CHU rules → workbench package (structural)** — captured 2026-05-06.  Should the CHU lint logic move to a focused `chumicro-checks` package, fold into `chumicro-workspace`, or stay in mono-repo `scripts/`?  Needs an ADR before CHU008 can land in the right home.  Bundles the speculative-public-API + cargo-cult-class-method candidates that share the same cross-repo-grep distribution problem.

- [ ] **Enable GitHub Copilot code review as a PR quality gate** (low priority — defer until community contributions begin).

- [ ] **Add digital I/O as the second library seam** (alongside CI/release work, not sequentially).

- [ ] **Explore test ergonomics — reduce repeated boilerplate across test files.**

- [ ] **Performance + resource benchmarking infrastructure** — measure heap + CPU per library operation with explicit GC control; per-benchmark thresholds that fail on regression; separate `bench` task or deeper test tier so slow benchmarks don't run on standard `test`; CI on a schedule.

## Out of scope (until revisited)

- CI-hosted device testing (`device-test.yml` / `workflow_dispatch`, CI-injected `devices.yml` / `workspace.yml` / `secrets.yml`). Parked over security concerns around shared-runner device access; bring back up before any design work resumes.
- CI simulation/emulation path (renode etc.). Not being explored until the above is revisited.

## Investigations

- [ ] **Investigate slow MicroPython RAM-mode functional test runs** — observed during 2026-04-19 live PyCharm testing that MicroPython RAM-mode functional tests took noticeably longer than expected.  CircuitPython RAM-mode is fast in comparison.  Suspects: per-file `mpremote mount` cost, cold-start interpreter overhead, batch-vs-per-test trade-off.  Profile against the new batch-execute path.

## Done (recent)

> **Where the detail lives.**  This section is a one-line pointer log.  Verbose session detail goes in commit messages, [`plans/history.md`](history.md) (dated entries), or [`plans/workstreams/<name>.md`](workstreams/) (per-phase acceptance).  Past entries link to those records — don't paste detail back into `next-up.md`.

- [x] **Plans-doc brevity sweep + CHU011 lint** (2026-05-07) — compacted `now.md` to ≤25 lines, swept `next-up.md` Now/Next paragraph-bodies into one-liner Done pointers, added agent-managed cross-maintenance banner, landed CHU011 lint capping each top-level bullet at 5 bullet points.
- [x] **Silent-skip test audit** (2026-05-07, commits [`96a6736`](https://github.com/ChuMicro/ChuMicro/commit/96a6736)..[`08f637f`](https://github.com/ChuMicro/ChuMicro/commit/08f637f)) — eight phases eradicated four shapes of silent PASS in `libraries/*/{tests,functional_tests}/`; `chumicro_test_harness.skip(reason)` primitive + `__chumicro_features__` capability marker + CHU009/CHU010 lint + Decision [0058](decisions/0058-test-skips-must-be-loud.md).  Adjacent: chumicro-mqtt 0.3.0 dropped silent fallback ([`3d0ade9`](https://github.com/ChuMicro/ChuMicro/commit/3d0ade9), [`e8d54f6`](https://github.com/ChuMicro/ChuMicro/commit/e8d54f6)).
- [x] **scripts/ ↔ workbench/ ↔ workspace-template config unification** (2026-05-04) — five-phase config convergence across both repos; `devices.yml` empty-registry shape, library config manifests, `workspace.yml` + `secrets.yml` workbench-owned starters, conftests via `compose_runtime_config()`, `chumicro-workspace 0.7.0` exposes `materialize_workbench_starters`.  Detail: [`workstreams/archive/scripts-workbench-config-unification.md`](workstreams/archive/scripts-workbench-config-unification.md).
- [x] **Two-file workspace config** (2026-05-04) — Decision [0057](decisions/0057-two-file-config.md): `!secret` marker retired; `workspace.yml` + per-project `config.toml` deep-merged via `compose_runtime_config(workspace_yaml, project_config)`.  Mono-repo gained `_workspace_template/workspace.yml`; setup runs `materialize_templates` → `materialize_workbench_starters`.
- [x] **On-device functional tests dogfood `chumicro_config.load_runtime_config()`** (2026-05-06) — migration shipped incrementally as Decision 0056 + scripts-workbench-config-unification + config-shape-beginner-ergonomics carried the seven on-device test rewrites along.  chumicro-pytest-device 0.4.0 ships `set_runtime_config`.  Detail: [`workstreams/archive/on-device-config-dogfooding.md`](workstreams/archive/on-device-config-dogfooding.md).
- [x] **Config-shape beginner ergonomics** (2026-05-06) — across mono-repo `30e2878` / `8303d17` / `7d36f27` + template-repo `72c6ffb`.  Three files (workspace.yml machinery / secrets.toml device-bound / project_config.toml per-project), flat-key `RuntimeConfig`, `WifiConfig.from_config`, manifest format, `config-validate` CLI, additive setup re-apply.  Bumps: chumicro-config 0.2.0, chumicro-wifi 0.1.0, chumicro-workspace 0.12.0.  Detail: [`workstreams/archive/config-shape-beginner-ergonomics.md`](workstreams/archive/config-shape-beginner-ergonomics.md).
- [x] **Finding 3 — `add-device` firmware-version parser breaks on RC builds** (2026-05-06, `8ecf728`) — walk the version tuple element-by-element and stop at first non-int; both probe and parser unified.
- [x] **Finding 4 — `add-device` suggests IDs from probed `board_id`** (2026-05-06, `f5539e9`) — reused Step 4 of beginner-onramp's bootstrap-wizard id-suggestion path.
- [x] **Finding 5 — `deploy <name>` auto-detects boot-shim mode** (2026-05-06, `3fde27c`) — `app.py` with a `run()` callable triggers a synthesised three-line `code.py` / `main.py` entrypoint, no flag required.
- [x] **Finding 6 — mpremote orphan port-holders block subsequent deploys** (2026-05-06, `224c489`) — port-busy failure mode now reports the offending PID so the user can `kill <pid>` decisively.
- [x] **Setup: schema reconciliation for user-edited config files** — Strategy B shipped 2026-05-04 (`chumicro_workspace.starter_drift` diff-only diagnostic); Strategy C shipped 2026-05-06 in `7d36f27` (`additive_apply.additive_reapply` comment-preserving append for workspace.yml + secrets.toml).  Detail: [`workstreams/archive/setup-schema-reconciliation.md`](workstreams/archive/setup-schema-reconciliation.md).
- [x] **Beginner-comfort onramp Phases 1 + 2 + audit-of-the-audit** (2026-05-02) — non-breaking foundation (CP `radio=` auto-detect, runner-tick reframe, root README rewrite, single canonical INSTALL.md, dependency-graph SVG, CONTRIBUTING trim) + breaking renames (`thing` → `project`, `libs/` → `shared/`) + audit-of-the-audit (Tier 1 small wins + ADR 0047 default `deploy_mode flash`).  Detail: [`workstreams/beginner-onramp.md`](workstreams/beginner-onramp.md).
- [x] **README hero pass 2 — un-bury the matrix** (2026-05-03) — restored library + workbench matrices to root README; killed marketing-philosophy framing + heartbeat-vs-sleep.svg; hero is one concrete LED-blinking promise.  Doc-writing-taste lessons in user-memory `feedback_doc_writing_taste.md`.
- [x] **Preflight phase-level parallelism — 31 s → 21 s, ~34 % faster** (2026-05-03) — ADR 0048; 11 unit-test phases run as concurrent `python scripts/run.py <subcommand>` subprocess re-invocations behind a 4-worker `ThreadPoolExecutor`; `--phase-workers` / `--package-workers` flags.
- [x] **Cross-runtime test recovery — 365 → 1147 tests passing on each unix-port** (2026-05-03, commits `8bd7f14`..`3e392df`) — source-side fixes (FakeSocket deque, BlockingIOError, UnicodeDecodeError, CaseInsensitiveDict insertion order); test-side `import pytest` removal; renamed CPython-only files to `_pytest`; CP unix-port gained `MICROPY_PY_SSL=1`; harness `raises(match=...)` + class-grouped test discovery + ImportError-fails-loudly contract.
- [x] **Heap-fragmentation test methodology** (2026-05-03) — root cause was test-file imports (~1000-line modules with bytes literals + dict fixtures + per-test function objects); library code is clean.  Shipped subprocess-per-file isolation in test harness + delta-based assertions across requests / http_server / websockets fragmentation tests; restored requests `many_headers` 30×50 workload.
- [x] **Decision 0044 — deploy-time runtime-file filtering** (2026-05-02) — extends Decision 0037 marker filter from bundle pipeline to every host-side deploy path; transports own runtime as part of identity; no escape hatch.
- [x] **Shared per-runtime adapter-selection helper plan dropped** (2026-05-02) — wifi unification (commit `0304542`) collapsed the wifi ladder to 3-way; only kvstore's ladder remains and its backends aren't slight variants of one API; substrate-aware logic belongs inside the adapter.
- [x] **`.scratch/run_*_acceptance.py` runners retired + library-self-declared deploy-mode constraints abandoned** (2026-05-02) — multi-thing path dropped; pinned-CA HTTPS test salvaged into `requests/functional_tests/test_real_get_tls.py`; existing `--deploy-mode flash` flag plus generic `INSUFFICIENT_MEMORY` recovery plan are sufficient.
- [x] **chumicro-wifi: unified MP adapter** (2026-05-02, `0304542`) — `MpEsp32WifiAdapter` + `MpRp2WifiAdapter` collapsed into substrate-aware `MpWifiAdapter`; auto-detects via `try: import esp32`; chumicro-wifi 0.0.2 → 0.0.3.  Substrate-API-shape lesson lifted to [`learnings.md`](learnings.md).
- [x] **`agent_strictness` decorative config field removed** (2026-05-01) — parsed since Phase 5 but had no consumer; AST-level checks need their own design pass; per no-speculative-public-API rule.
- [x] **Workspace-ecosystem Phase 2f closed — per-thing `deploy_targets:` + `--all-things`** (2026-05-01, mono-repo `ec1d133`, chumicro-workspace 0.0.3, template-repo [`4607864`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/4607864)) — sister of `--all-devices`; `_build_deploy_plan` extraction; 24 new tests.
- [x] **Workspace template examples audit closed** (2026-05-01, [`e8854fe`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/e8854fe)) — fixed two real bugs in `wifi_only/app.py` `.value` access + 5 `is` / `is not` comparisons across four examples.
- [x] **CP wipe → ready: poll for FAT volume to be usable** (2026-05-01) — `_wait_for_circuitpy_remount()` polls `_resolve_circuitpy_drive` until it returns cleanly or 10 s budget exhausts; chumicro-deploy 0.4.2 → 0.4.3; soak 4/4 on the four-board canonical matrix.
- [x] **Multi-CIRCUITPY-drive volume-name shuffle on wipe** — disproved 2026-05-01.  UIDs stayed pinned to original mount paths across two soak runs.  Real bug was a host-side timing race; fix shipped same day in chumicro-deploy 0.4.3.
- [x] **Lolin S2 CP appears to need manual reset post-wipe** — could not reproduce 2026-05-01.  Original observation was a single transient.
- [x] **CP `wipe_filesystem()` reconnect now poll-and-retry** (2026-04-30, `9da3680`) — 2 s seed + 30 s polling reconnect (0.5 s interval) replaces the unconditional 5 s settle; chumicro-deploy 0.4.0 → 0.4.1.
- [x] **chumicro-repl audit pass — five-phase landing** (2026-04-29, squash `2ff929d`) — Tab completion + line-mode default + README/guide refresh + `run_loop` triple-recovery dedup + `coached_session_start` building block + 4-board hardware sweep.  chumicro-workspace 0.0.1 → 0.0.2.
- [x] **`_ticks_ms` shim sweep + msgpack-1.1.2 drift fix** (2026-04-29) — `fecbc4c` gated chumicro-msgpack native delegation to CP only (PyPI msgpack 1.1.2 silently drifted on CPython); `1ee6a88` replaced per-file `_ticks_ms()` shim in six functional tests with `chumicro_timing.ticks_ms`.
- [x] **`pytest_device` deploys `_test_creds.py` alongside functional tests** (2026-04-28, `ff6f1ec`) — `transport.stage()` gained an `extra_modules` keyword arg; surfaced + fixed two real follow-on bugs the silent-skip masked (`WifiService.adapter.radio` accessor, MP UDP `sendto` rejecting hostnames).
- [x] **Unify CP file-manipulation through one path (rsync vs `Path.write_bytes`)** (2026-04-28) — both `transport.deploy_files` (production) and `transport.stage` (functional tests) go through `flash_drive.rsync`; validated empirically via 10-iteration bake test on Pi Pico W CP.
- [x] **CP raw REPL parser race on long-running test chunks** (2026-04-28) — `_read_until` now uses idle-timeout semantics; the malformed-raw-REPL-response failure on long mqtt round-trips is fixed; both MP boards pass QoS 1 round-trip end-to-end.
- [x] **CP MQTT functional test hangs on TCP connect to host mosquitto** (2026-04-28) — test-only bug; clock-domain mismatch in microseconds.  Test's local `_ticks_ms()` derived ms from `time.monotonic() * 1000` (unwrapped) while MQTT's deadlines came from `chumicro_timing` (29-bit-wrapped per Decision 0008).  Fix replaced the test shim with `chumicro_timing.ticks_ms`; library faithfully honors caller-supplied `now_ms` per Decision 0014.
- [x] **Multi-thing-staging replacement closed** (2026-04-27) — three-commit workstream replacing retired `multi_thing_boot_source` path: `b2d16b3` (transport `deploy_diff` + `list_files_in_scope` + `delete_files`); `a7955fd` (workspace CLI wiring); `--wipe` flag (CP `storage.erase_filesystem()` + MP recursive walk).
- [x] **Workspace ecosystem Phase 7 closed** (2026-04-27) — Richer REPL: line-mode wrapper + persistent history (Slice 1a, `abc81ff`); LineModeContext + `:edit` / `:save` / `:load` / `:snippets` (Slice 1b, `835eb5c`); completion module + KeywordCompleter + DeviceCompleter scaffolding (Slice 1c).  Detail: [`workstreams/repl-playground.md`](workstreams/repl-playground.md).
- [x] **Workspace ecosystem Phase 6 closed** (2026-04-27) — Cross-repo documentation audit pass after Phases 1+2+4+5; mono-repo + template repo doc updates.
- [x] **Workspace ecosystem Phase 5 closed** (2026-04-27) — `quality:` block in `workspace.yml` wired through; new `chumicro_workspace.quality` module reads + validates; `_cmd_lint` reads `lint.enabled` / `lint.select`; `_cmd_test` prepends `--cov-fail-under=<n>`.
- [x] **Workspace ecosystem Phase 4 closed** (2026-04-27) — Library scaffolder migration: `scripts/new_library_scaffold.py` → `chumicro_workspace.scaffold`; templates relocated to `_payloads/library_template/`; CLI gains `python run.py new --library <name>`.
- [x] **Workspace ecosystem Phase 2 closed** (2026-04-27) — Six commits: `repl <thing>` (`333d900`) + `status` (`7697deb`) + `deploy --dry-run` (`f2a055d`) + deploy-failure hints (`93b7c7a`) + `doctor` (`045f819`) + `deploy --all-devices` (`139b0ee`).  New `chumicro_workspace.{health,recovery}` modules.
- [x] **Workspace ecosystem Phase 1 closed** (2026-04-27) — Nested things + examples + drop `switch` shipped across mono-repo `98fa8d0..c8a05fe` and template-repo `4523c89..98b6377`.  Detail: [`workstreams/archive/nested-things-and-examples.md`](workstreams/archive/nested-things-and-examples.md).
- [x] **Workspace-template testing-infrastructure audit closed** (2026-04-27) — Phase A to template repo ([`579274a`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/579274a)); Phase B to chumicro (`f47acba`).  Template gained ruff config + coverage gate + dev extras + parametrized workspace tests + `_template/` test scaffold + `.github/workflows/test.yml`.
- [x] **Scripts → workbench Phase 1 + 2 closed** (2026-04-27) — Phase 1 (`e76b9f9`) migrated device-registry schema to `chumicro_deploy.config.default`; Phase 2 (`3e01cbf`) carved `chumicro-pytest-device 0.1.0` out of `scripts/{pytest_device,pr_summary,result_parser,device_testing}.py` (~2270 lines moved).
- [x] **chumicro-mqtt 0.1.4 + chumicro-sockets 0.1.4 — production-readiness sweep** (2026-04-26) — `recv_budget_per_tick` knob (default 1024 B) + `max_tx_queue_size` cap with `MQTTBackpressureError` (protocol-internal traffic bypasses); `ssl_context_with_ca` defaults to `CERT_REQUIRED` + multi-cert PEM bundles.  Lifted to [`learnings.md`](learnings.md).
- [x] **Phase 7: first end-to-end sensor thing — closed** (2026-04-26, `fa91f60..94561f7`) — `things/example_sensor/` exercises wifi → sockets → mqtt → kvstore → workspace stack on Pi Pico W MP; plain TCP + TLS+MQTT-with-`CERT_REQUIRED` both verified live.  Detail: [`workstreams/archive/phase-7-integration.md`](workstreams/archive/phase-7-integration.md).
- [x] **`scripts/device_config.py` consumes `chumicro_deploy.config.default.load_raw_entries`** (2026-04-26) — Decision 0032 rule 8 cleanup; new primitive parses YAML structure (no Device construction); script wraps the workbench loader instead of duplicating.
- [x] **Decision 0038 — workspace bootstrap via clone, not pip-installed scaffolder** (2026-04-26) — renamed `chumicro-workspace-runtime` → `chumicro-workspace`; folded `init` / `update` / three-zone manifest in; created [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) as canonical Git template; self-bootstrapping `run.py` + chumicro-dev mode.
- [x] **Pi Pico W flash-footprint workstream** (2026-04-26, `f8b28d6..f23a1c4`) — MQTT 8 → 4 file consolidation; `__chumicro_runtimes__` per-runtime CP-mpy / MP-mpy bundle filtering ([Decision 0037](decisions/0037-runtime-file-marking.md)); cross-library narrative-docstring trim; chumicro-deploy macOS-FAT hygiene fix.  All 9 libraries fit on Pi Pico W CP for the first time.
- [x] **Phase 6: `chumicro-mqtt` shipped** (2026-04-26) — Non-blocking MQTT 3.1.1 client (QoS 0+1) at `libraries/mqtt/`; runner-shaped; per-`packet_id` `InFlightTable`; `WhenOversized` policy.  139 host tests at 94 % cov + 6 live Mosquitto integration + 6 tracemalloc memory-pressure; on-board perf 0 bytes net heap drift across the four-board matrix.
- [x] **Phase 5: `chumicro-sockets` shipped** (2026-04-25) — Cross-runtime TCP+TLS client per Decision 0031; 3 adapters + `TCPClientSocket` protocol + `FakeSocket` test fake; 40 host tests at 95 % cov.
- [x] **Phase 4b: `chumicro-workspace-template` shipped (minimum-viable)** (2026-04-25) — workbench scaffolder + updater package with built-in default template payload (11 starter files); three-zone model from Decision 0029 §9 generalized across the whole tree.
- [x] **Phase 4a polish closed** (2026-04-25) — Multi-thing-on-one-device deploys + `switch <name>` CLI + `things` CLI + live-board functional tests for the boot-shim chain + README + guide rewrite.  See [`history.md` 2026-04-25](history.md).
- [x] **MP firmware scrape bug-fix** (2026-04-25) — preview-filename suffix capture + Adafruit Feather ESP32-S2/S3 entries removed from curated map.
- [x] **Phase 4a: `chumicro-workspace` shipped** (2026-04-25) — Seven slices closed Phase 4a end-to-end across config-merge core, FileSource decorator, CLI, `devices.yml` round-trip, board-state onboarding, firmware URL derivation, import-graph resolver, and device-side `workspace_runtime` boot module.  268 host tests at 96 % cov.  Detail: [`workstreams/archive/project-workspace.md`](workstreams/archive/project-workspace.md).
- [x] **Phase 3a: `chumicro-wifi` shipped** (2026-04-25) — 4 adapters + state machine + reconnect supervisor; 87 host tests at 99 % cov; per-substrate functional + lazy-loading + live-AP acceptance pass on all four boards.
- [x] **Phase 3b: `chumicro-kvstore` shipped** (2026-04-25) — Decision [0034](decisions/0034-kvstore-api-and-backends.md) + 4 backends (memory / CP NVM with CRC framing / MP NVS / MP LittleFS); 92 host tests at 99 % cov; 27 functional tests pass on each of the four plugged-in boards.
- [x] **Static gate for libraries/ absolute-imports rule** (2026-04-25) — ruff TID252 enabled with per-file-ignores relaxing it for `workbench/`, `scripts/`, tests, functional_tests, examples.
- [x] **`check-version` + `check-api` cover workbench packages** (2026-04-25) — both pre-merge gates walk `workbench/*/` alongside `libraries/*/`; codified as `scripts/audit_gates.py` regression suite.  See [`history.md` 2026-04-25](history.md).
- [x] **`release.yml` + `promote.yml` cover workbench packages** (2026-04-25) — `workbench/*/VERSION` triggers + library-only bundle gating + kind-aware promote-validate.
- [x] **VS Code Testing-panel on-device validation + workbench-discovery + functional_tests show-but-deselect** (2026-04-25).  See [`history.md` 2026-04-25](history.md).
- [x] **Project-workspace Phase 2: `chumicro-repl` shipped** (2026-04-25).  See [Phase 2 archive](workstreams/archive/project-workspace.md).
- [x] **VS Code first-open hardening** (2026-04-24) — `.vscode/extensions.json`, tasks switched to `${command:python.interpreterPath}`, `chumicro_deploy.host_platform` audit.
- [x] **`chumicro-deploy` config schema renamed to claim ownership** (2026-04-24) — `config/chumicro.py` → `config/default.py`; registry key `"chumicro"` → `"default"` per Decision 0032 rule 8.
- [x] **`chumicro-deploy` review sweep + pytest unification of `test-libraries-functional`** (2026-04-24).
- [x] **`run.py` command-naming audit + `test-workbench-functional` task** (2026-04-24).
- [x] **`chumicro-deploy` recovery-layer hardening + macOS FSKit wedge detection** (2026-04-23).
- [x] **Project-workspace Phase 1: `chumicro-deploy` extraction** (Decision 0029 + Decision 0032, 2026-04-22).  Detail: [Phase 1 archive](workstreams/archive/project-workspace.md).
- [x] **`chumicro-deploy` interactive recovery layer** — `InteractiveDeployer` + `classify_deploy_failure` + ten `DeployFailureKind`s including `MACOS_FSKIT_WEDGED` (added 2026-04-23).
- [x] Docs and planning sync for device testing and IDE workflows.
- [x] Device-testing UX refinements — `test-libraries-functional` uses `devices.yml` defaults; `--micropython-device` / `--circuitpython-device` replace legacy `--device`; CP-RAM bootstraps chunked against live free-heap.
- [x] Device testing Phase 3: IDE integration — `scripts/pytest_device.py` routes explicit `functional_tests/` targets via `devices.yml` (Decision 0027).
- [x] Deep developer test sweep — `test-everything` superseded by `preflight --with-functional` and `test-functional` (2026-04-24 rename audit).
- [x] CircuitPython flash/RAM hardening — bulk-stage rsync, soft-reset between groups, FAT32 race fixes, `os.sync()`, `__pycache__` exclusion, raw-REPL re-entry, RAM bootstrap chunking, batch execution.
- [x] Whitespace linter (CHU002–CHU005) wired into `run.py lint`.
- [x] Scripts consolidation — `ensure_build_tools` → `shared.py`; `load_tomllib`, `GITHUB_ORG`, `discover_library_dirs`, `read_pyproject_description`, `discover_doc_dirs`, `is_ref_reachable` → `workspace.py`.
- [x] Support package rename — `support/testing/` → `support/abstractions/` (`chumicro_abstractions`); now exports `FakeTime` only.
- [x] Editable-install support packages — `install_editable()` installs both publishable libraries and support packages; legacy `_ensure_support_importable()` runtime `sys.path` fallback removed.
- [x] Deploy modes: RAM and flash (Decision 0028) — `--deploy-mode ram|flash`; CircuitPython flash transport (USB drive copy); `circuitpy_drive_path` field; bootstrap routing.
- [x] Device testing Phase 2: CircuitPython serial transport — `CircuitpythonTransport` (pyserial raw REPL) + `build_circuitpython_bootstrap` + orchestrator routing.
- [x] Device testing infrastructure Phase 1 (Decision 0027) — `device_config.py`, `result_parser.py`, `support/device_transport/` with `MicropythonTransport`, `name_filter` on `runner.run_module`, real `test-libraries-functional` orchestration.
- [x] Populate "What's new" sections in library guides — all four libraries now have version entries.
- [x] CI build and cache optimizations: `--no-isolation` build (~7x faster), MicroPython submodule pruning (87 % cache size reduction), explicit pip caching for docs deploy.
- [x] Documentation sync: run.py commands synced across README, AGENTS.md, and development-cli.md.
- [x] Validate-mpy CI job for PRs: builds mpy-cross, stages all libraries, validates mip install + import from staged bundle.
- [x] Pre-publish bundle validation: `--staging-dir` mode validates mip install against locally staged bundles before pushing to live repos; integrated as a gate in `release.yml` + `promote.yml`.
- [x] Mip install validation in CI: `validate-mip` job tests mip install + import for both `.py` and `.mpy6` formats after every bundle push.
- [x] Mpy folder restructuring (Decision 0024): `.mpy` bytecode moved out of root package dirs into `mpy6/` (MicroPython) and `circuitpython-10.x-mpy/` (CircuitPython).
- [x] Mip dependency routing: experimental `package.json` references experimental bundle repo for deps.
- [x] CI mpy-cross integration: `release.yml` + `promote.yml` build both mpy-cross compilers from source (cached); both CP + MP `.mpy` files compiled during bundle staging.
- [x] Promote workflow fixes: inlined stable docs deployment (concurrency group was silently canceling deploys); attestations to stable PyPI publish; bundle release description fix.
- [x] CI micropython cache sharing: `validate-mpy`, `runtime-compatibility`, `release.yml`, and `promote.yml` all share the same micropython cache key.
- [x] Docs branding overhaul: warm palette matching badger logo, favicon regeneration, landing page reads descriptions from pyproject.toml, plain-language library descriptions.
- [x] Library README overhaul: absolute URLs for PyPI compatibility, badger tip images, Source links, README.md included in bundle staging, scaffold template aligned.
- [x] Brand normalization: "Chumicro" → "ChuMicro" across 50+ occurrences in prose, docstrings, templates, and docs.
- [x] Contributor fork workflow: complete fork-to-PR walkthrough in CONTRIBUTING.md, fork sync/rebase guidance, GitHub UI steering for PRs.
- [x] Contributor experience audit v4: "First contribution?" signpost, Contributor FAQ, "abbreviations we spell out" reframing, memory-pattern reassurance repositioning, AGENTS.md working-style consolidation.
- [x] Test harness heap deltas: per-test allocation tracking with manual GC control.
- [x] Plans cleanup: removed `plans/sessions/`, commit history is the primary context recovery mechanism.
- [x] Scripts test suite: 203 pytest tests for scripts/ infrastructure, `test-scripts` subcommand integrated into preflight.
- [x] IDE audit: scripts/ added to source roots, test discovery, and extraPaths in PyCharm and VS Code configs.
- [x] Contributor experience audit v3: root README "Your first program" example + REPL snippet, circup bundle explanation, install section cleanup, common-mistakes FAQ, FakeTicks.ticks_add overflow validation, self-contained testing.py constants, architecture guide, editable-install clarification.
- [x] Enable GitHub Discussions (Q&A, Ideas, Show and Tell categories).
- [x] Contributor experience audit v2: README reorder, dependency graph, cross-library references (timing ↔ runner), "What's new" sections, PR template simplification, coverage hint in `run.py`, `CLAUDE.md` and `.cursorrules` pointers, GitHub Discussions link.
