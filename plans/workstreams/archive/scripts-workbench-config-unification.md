# Workstream: scripts/ ↔ workbench/ ↔ workspace-template config unification

Status: **closed** — Phases 1, 2, 3, 4, 5 shipped 2026-05-04 (mono-repo) plus the matching workspace-template repo half ([`a9bb4bd`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/commit/a9bb4bd)).  Phase 4.5a (`!secret` simplification) closed by [Decision 0057](../../decisions/0057-two-file-config.md).  Phase 4.5b (on-device test code dropping `_test_creds.py`) carved out as its own peer workstream 2026-05-05 once this parent closed and the upstream config-shape questions landed; transport `extra_files` API foundation shipped via [Decision 0056](../../decisions/0056-transport-extra-files-staging.md); conftest + plugin + on-device migration covered in [`plans/workstreams/on-device-config-dogfooding.md`](on-device-config-dogfooding.md).

## Premise

The mono-repo (`chumicro/`) and the workspace-template repo (`ChuMicro-Workspace-Template/`) both manage two cross-cutting things — a `devices.yml` board registry and a per-thing config pipeline — but with **two different shapes** today.  The workbench packages (`chumicro-workspace`, `chumicro-deploy`, `chumicro-pytest-device`, `chumicro-config`) already own enough of the primitives that the two repos *could* share a single pattern.  They don't yet, because of historical sequencing (the mono-repo's flows predate the workbench packages they could now delegate to).

This workstream brings the mono-repo's flows in line with the workspace-template's, owned by workbench packages, with `chumicro-config` as the single runtime-config primitive both repos dogfood.

## Current state — the gap (verified 2026-05-04 by deep audit)

### Flow A — `devices.yml`

| Aspect | Mono-repo today | Template-repo today | Workbench owns? |
|---|---|---|---|
| Initial shape | Two `sample-{circuitpython,micropython}-board` pre-fills (zero callers; pure documentation) | Empty `devices: []`, null defaults | Schema reader (`chumicro_deploy.config.default.load_device_registry()`) |
| Population UX | Hand-edit | `chumicro-workspace add-device` (probes UID + board_id, three-zone-aware writes via ruamel.yaml) | Yes — `chumicro_deploy.config.devices_yaml.add_device` exists; mono-repo doesn't use it |
| Hardware identity | Not tracked (no `hardware:` block) | Tracked (`hardware.{uid,machine,board_id,firmware_source}`) | Schema in `devices_yaml.HARDWARE_BLOCK_ZONES` |
| `ide_runtime` field | Present (controls pytest-device IDE play-button) | Absent in `_workspace_template/devices.yml` (but the schema reader already accepts it; should be added — workspace-template users who scaffold their own libraries via `python run.py new --library <name>` need IDE play-button targeting too, same as mono-repo contributors) | Reader silently passes through |
| Three-zone classification | None (flat user-owned) | USER-OWNED / HARDWARE-ONCE / PROBED-ALWAYS | `devices_yaml.{USER_OWNED_FIELDS, PROBED_ALWAYS_FIELDS, HARDWARE_ONCE_FIELDS}` |

### Flow B — workspace config (wifi, mqtt, etc.)

| Aspect | Mono-repo today | Template-repo today |
|---|---|---|
| Source file | `chumicro-dev-config.toml` (one TOML at repo root, gitignored) | `workspace.yml` (committed) + per-project `config.toml` (committed) + `secrets.yml` (gitignored) |
| Inheritance | None — each test conftest reads it independently | Workspace-yaml `defaults:` deep-merges into project `config.toml` at deploy time; project wins at any depth |
| Secret marker | None (creds in plain text in the gitignored TOML) | `password = "!secret <name>"` references `secrets.yml` entries |
| Consumed by | `libraries/{wifi,requests,mqtt,sockets,http_server}/functional_tests/conftest.py` — each materializes a `_test_creds.py` module via host-side `tomllib` | On-device code via `chumicro_config.load_runtime_config()` from the deploy-baked `runtime_config.msgpack` |
| Validation | None (cryptic `KeyError` if creds missing) | `chumicro_config.load_section()` raises `MissingConfigKey` / `InvalidConfigType` per Decision 0036 |
| Library config requirements | Documented in prose READMEs only — no manifest | Same — prose only |

The two flows are **different solutions to the same problem**: "what wifi (or mqtt or …) does this code use?"  Decision 0030 §config-vs-state already framed the user-side answer; the mono-repo's functional tests just predate the framing.

### Why now

1. The 2026-04-27 Phase 4 migration (workspace-ecosystem workstream) already moved the library scaffolder out of `scripts/` into `chumicro_workspace.scaffold`.  The pattern works.
2. [69fec7f](https://github.com/ChuMicro/ChuMicro/commit/69fec7f) cleaned the residue from that migration — the dead 11 templates in `scripts/templates/`.  The remaining 7 mono-repo-only templates are correctly placed.
3. With `chumicro-config` (Decision 0036) shipped and used by every networking library's user-facing `from_dict()`, the mono-repo's functional tests are the **only** code path in the entire ecosystem that still reads creds via a non-`chumicro-config` mechanism.  Dogfooding gap.
4. Library config requirements are nowhere machine-readable — a user setting up a new project has to read every library's README to know what `[wifi]` / `[mqtt]` keys are required.

---

## Decision record

The decision this workstream executed has been promoted to [Decision 0055](../../decisions/0055-config-pipeline-unification.md) (`accepted`, 2026-05-04).  Phase 4.5a (`!secret` simplification) was promoted to its own [Decision 0057](../../decisions/0057-two-file-config.md).  Phase 4.5b on-device dogfooding is now its own peer workstream — [`../on-device-config-dogfooding.md`](on-device-config-dogfooding.md) — with transport `extra_files` API foundation shipped via [Decision 0056](../../decisions/0056-transport-extra-files-staging.md).  This workstream document captures the per-phase execution detail; the ADRs capture the durable why.

---

## Phase plan

### Phase 1 — `devices.yml` convergence

**Scope (mono-repo half — done in this workstream):**
- Replace `scripts/templates/devices.yml.template` body with the empty-registry + three-zone-headed shape from `_workspace_template/devices.yml`.  Keep `ide_runtime: micropython` in the `defaults:` block — same field, kept in both repos for the unified library-author IDE flow.
- Drop the two `sample-*-board` entries.  Verified zero tests / CI steps reference the IDs.
- Relax `chumicro_deploy.config.default.load_device_registry` to accept an empty `devices: []` registry — return `([], defaults)` instead of raising.  Workspace-template repo already starts from this state at clone time; mono-repo will too after this phase.  Callers that need at least one device check the list themselves with context-specific messages (pytest-device's plugin already does this at line 1098).
- Wire `python scripts/run.py add-device` as a thin shim around `chumicro-workspace add-device`.
- Add a minimal `workspace.yml` at mono-repo root (committed) so `chumicro-workspace`'s workspace-discovery walk finds the mono-repo as a valid workspace.  Phase 1 ships only an empty `defaults: {}` block + a header comment pointing at Phase 3 / 4 for full content (wifi/mqtt creds, secrets pipeline, library-source overrides).  Pulled forward from Phase 3 because the `add-device` shim depends on `WorkspaceLayout.from_dir()` succeeding.
- Update `python scripts/run.py setup` to print a "next: run `add-device` to register your boards" hint when `devices.yml` is materialized empty for the first time.
- Update `scripts/tests/test_generate_config_files.py` to match the new empty-registry contract.
- Update `docs/contributing/device-testing.md` + `CONTRIBUTING.md` for the new flow.

**Workbench-payload consolidation (added mid-Phase-1 after user pushback):**
- The user asked: "Why does the template repo need a devices.yml template?  Can't this be a shared workbench item with the mono-repo?"  Answer: yes.  The canonical starter content is now owned by `chumicro-workspace` at `_payloads/devices_yml/starter.yml.template`, exposed via `chumicro_workspace.read_devices_yml_starter()`.  Mono-repo's `scripts/generate_config_files.py` materializes `devices.yml` from this reader (no longer from `scripts/templates/devices.yml.template` — that file is deleted as residue).  Single source of truth.

**Workspace-template half (small follow-up after this phase lands):**
- Add `ide_runtime: micropython` to `_workspace_template/devices.yml`'s `defaults:` block so workspace-template users who scaffold their own libraries get the same IDE play-button targeting as mono-repo contributors.  Fully additive — schema reader already accepts the field.
- Replace `_workspace_template/devices.yml` itself with a call to `chumicro_workspace.read_devices_yml_starter()` from the template repo's setup flow, so the template repo also materializes from the workbench payload instead of carrying its own static copy.  Deletes residue, completes the unification.

**Files touched (mono-repo):** ~6.  Estimated 1 session.

### Phase 2 — library config manifests *(done)*

**Scope (executed):**
- The plan's "8 libraries" estimate was wrong — only `chumicro-wifi` actually consumes `chumicro-config.load_section` today.  Per the no-speculative-API rule, the manifest format applies only where there's a real consumer.  Phase 4 will add manifests as it migrates more libraries onto the runtime-config pipeline.
- `[tool.chumicro.config]` block added to `libraries/wifi/pyproject.toml`.  Schema (simplified mid-implementation when TOML's "same key declared twice" rule made the `sections = [...]` array + `[...sections.<name>]` table forms collide):
  ```toml
  [tool.chumicro.config.sections.wifi]
  required = ["ssid", "password"]
  optional = ["hostname", "connect_timeout_ms", ...]
  ```
  Section names inferred from the table keys.  Empty section table is valid (forward-compat).
- New `chumicro_workspace.config_manifest` module — `read_manifest`, `aggregate_manifests`, `validate_runtime_config`, `find_library_roots` plus dataclasses (`SectionManifest`, `ConfigManifest`) + error type (`ConfigManifestError`).  Aggregator unions `required` sets across libraries (any library's "must have" wins) and promotes optional→required when libraries disagree (correctness over permissiveness).  Validator collects every problem in one multi-line error so deploy-time failures don't ping-pong.
- `WithRuntimeConfig` extended with optional `library_roots` parameter.  When provided, `files()` reads each library's manifest, unions, and validates the merged-and-resolved config dict before writing the msgpack — turning "config mismatch lands on device, fails at boot with cryptic `MissingConfigKey`" into precise deploy-time failures.
- `project_import_graph_source` and `project_boot_with_import_graph_source` extract library roots from their search paths via `find_library_roots()` and pass them through to `WithRuntimeConfig`.  Real consumer for the validator from day one — every import-graph deploy in mono-repo + workspace-template now validates against installed library manifests.
- Tests: 31 new in `test_config_manifest.py`; 2 new in `test_deploy_source.py` (validation pass + validation fail); 1 cross-cutting in `test_config_manifest.py::TestRealMonoRepoManifests` reads the real `libraries/wifi/pyproject.toml` and asserts the manifest matches `WifiConfig.from_dict`'s required/optional surface — drift on either side fails this test.

**Phase 4 will extend this** — as more libraries gain `chumicro-config`-shaped from_dicts (when functional tests dogfood the runtime-config pipeline), each adds its own `[tool.chumicro.config.sections.<name>]` block.  No additional plumbing needed; the manifest module already aggregates across multiple libraries.

**Known limitation (refine in Phase 4):** `find_library_roots` uses the import graph's static *search paths*, not the actually-imported modules.  A workspace with chumicro-wifi available but a project that doesn't import it would still validate against wifi's manifest.  Today this is correct (wifi is the only manifest holder; if it's available a project really should set wifi config).  Phase 4 refines this when validating against an "actually imported" subset becomes meaningful.

### Phase 3 — mono-repo workspace root config *(done)*

**Scope (executed):**
- `workspace.yml` at mono-repo root populated with `[defaults.wifi]` (ssid + `!secret wifi_password` reference), `[defaults.mqtt.broker]` (host: `test.mosquitto.org`, port: 1883), commented-out `library_sources:` / `deploy_targets:` / `quality:` blocks documenting the full shape.  Mirror of the workspace-template repo's `workspace.yml` plus mono-repo-specific defaults (`mqtt.broker` for `libraries/mqtt/functional_tests/test_real_*.py`).
- New `secrets.yml` starter content owned by `chumicro-workspace` at `_payloads/secrets_yml/starter.yml.template`, exposed via `chumicro_workspace.read_secrets_yml_starter()`.  Same workbench-payload pattern Phase 1 applied to `devices.yml` — single source of truth shared between the mono-repo and the workspace-template repo.
- `scripts/generate_config_files.py` materializes both `devices.yml` and `secrets.yml` from the workbench payloads (de-duplicated via a shared `_materialize_from_workbench` helper).  `chumicro-dev-config.toml` still materialized from `scripts/templates/` until Phase 4 retires it.
- `.gitignore` gains `secrets.yml`.  `workspace.yml` is *not* gitignored (committed — no secrets in it; secrets live in `secrets.yml` referenced via `!secret`).
- Tests: 4 new in `test_secrets_yml_starter.py`; 1 new in `test_generate_config_files.py` covering the workbench-payload materialization.
- `docs/contributing/device-testing.md` rewritten — old "device-config.yml" section (which was already stale; the actual file was `chumicro-dev-config.toml`) replaced with the unified workspace.yml + secrets.yml flow plus a "Legacy: chumicro-dev-config.toml" subsection explaining the Phase 4 migration.

**Workspace-template half (small follow-up after Phase 3 lands):**
- The workspace-template's `_workspace_template/secrets.yml` is now stale residue.  Once the template repo's setup flow gains a call to `chumicro_workspace.read_secrets_yml_starter()`, that static file can be deleted.  Mirrors the equivalent follow-up for `_workspace_template/devices.yml` (Phase 1's deferred half).

**Phase 4 next steps that this enables:**
- Functional-test conftests (`libraries/{wifi,requests,http_server,mqtt,sockets}/functional_tests/conftest.py`) migrate from `chumicro-dev-config.toml` → `workspace.yml + secrets.yml + per-library config.toml + chumicro-pytest-device's bake-config flag`.
- `chumicro-dev-config.toml.template` deleted; the legacy materialization in `generate_config_files.py` removed.
- The `_test_creds.py` materialization pattern across every networking-library conftest deleted in favor of `chumicro_config.load_runtime_config()`.

### Phase 4 — functional tests dogfood the unified config sources *(done)*

**Scope (executed — narrower than the original draft):**

The original draft had the on-device test code call `chumicro_config.load_runtime_config()` directly (full dogfooding of the user-facing path).  That requires `chumicro-pytest-device` to stage a binary `runtime_config.msgpack` onto the device alongside the test files, which means extending `transport.stage()`'s API to accept `extra_files: dict[str, bytes]` — a transport-API change that touches CP / MP / fake transports and warrants its own decision pass.  Splitting the cost-benefit by half:

- **What landed in Phase 4:** every networking-library functional-test conftest now reads the unified config sources (`workspace.yml` + per-library `functional_tests/config.toml` + `secrets.yml` via `chumicro_workspace.compose_runtime_config`).  The `_test_creds.py` materialization pattern stays, but the data flowing into it comes from the unified pipeline instead of the legacy `chumicro-dev-config.toml`.  Half the dogfooding (host-side data flow) — sufficient to retire the legacy file.
- **Deferred to a follow-up phase:** the on-device test code dropping the `_test_creds.py` import in favor of `from chumicro_config import load_runtime_config; config = load_runtime_config()`.  Gated on the transport-API change.

**Files touched (this phase):**

- New `chumicro_workspace.pipeline.compose_runtime_config()` — the dict-only sibling of `build_runtime_config`.  Conftest fixtures need the merged dict in memory; the deployer needs the msgpack on disk.  Both call the same underlying loaders + merger + secrets resolver; `build_runtime_config` is now a thin wrapper.  2 new tests in `test_pipeline.py`.
- Every networking-library conftest (`libraries/{wifi,requests,http_server,mqtt,sockets,websockets,ntp}/functional_tests/conftest.py`) rewired:
  - Drops `tomllib.loads(_DEV_CONFIG.read_text())`.
  - Adds `compose_runtime_config(workspace_yaml, library_config, secrets_yaml)` call.
  - Reads `merged["wifi"]["ssid"]` / `merged["wifi"]["password"]` instead of `data["wifi"]["ssid"]`.
  - Treats the placeholder SSID `"replace-with-your-ap-ssid"` as "no creds yet" (silent-skip path).
  - Library-specific extras (mqtt broker spawn, sockets UDP echo, websockets PyPI server) preserved unchanged.
- `scripts/templates/chumicro-dev-config.toml.template` deleted.  `scripts/generate_config_files.py` simplified — no more `_CONFIGS` list (devices.yml + secrets.yml are workbench-payload only).
- `.gitignore` keeps `chumicro-dev-config.toml` for one cycle so contributors with a left-over copy don't accidentally commit it.
- Docs refreshed: `docs/contributing/device-testing.md` drops the "Legacy: chumicro-dev-config.toml" subsection (no longer applies); `development-{pycharm,vscode}.md` stop mentioning the file; `libraries/wifi/functional_tests/test_acceptance.py`'s docstring updated.

**Phase 4.5 (deferred, see above) does the second half:** transport-API extension for binary file staging + on-device `load_runtime_config()` migration + `_test_creds.py` deletion.  Splits cleanly because the transport API change is structural and warrants a decision pass; this phase keeps the on-device test signature stable while flipping the host-side data source.

### Phase 4.5 — `!secret` simplification (deferred to a separate session)

### Phase 4.5 — `!secret` simplification (deferred to a separate session)

**User flagged 2026-05-04 (between Phase 3 + Phase 4):** the `!secret` indirection is over-engineered for the mono-repo's needs.  The pattern came from the workspace-template's "contributors commit their project structure but keep credentials local" use case; the mono-repo's "contributor wifi creds for functional tests" is a genuinely simpler problem and probably justifies a different shape.

Two paths the user is weighing:

1. **Drop in mono-repo only.**  Mono-repo's `workspace.yml` becomes gitignored, holds wifi/mqtt creds in plaintext, no `secrets.yml`, no `!secret` marker resolution.  Materialized from a workbench-owned starter the same way Phase 1 did `devices.yml`.  Walks back the Phase 3 design partially — drop `secrets.yml` materialization, drop the `!secret wifi_password` marker, put `password: replace-with-your-wifi-password` directly in the workspace.yml starter.  Workspace-template repo retains the three-file split (`workspace.yml` committed + per-project `config.toml` committed + `secrets.yml` gitignored, with `!secret` markers).  Two patterns coexist; "unification" is partial.
2. **Drop everywhere** (including the workspace-template's user-facing pattern).  Either user-facing `workspace.yml` + per-project `config.toml` become gitignored (loses the "commit your project structure, only secrets are local" property), or both repos accept that secrets travel with the same file as non-secret config.

**Lean from the side-chat:** drop in mono-repo only, pending the user's call on the template.

**Why this is deferred:** the lift is small (one workspace.yml content edit + drop the secrets.yml materialization in `generate_config_files.py` + delete the secrets.yml.starter payload + update gitignore + update tests), but it's a structural call about the unification premise — different from Phase 4's mechanical conftest migration.  Doing them together would muddy the commit story.  Phase 4 lands first using the current `!secret` shape; Phase 4.5 walks it back if/when the user picks path 1.

### Phase 5 — IDE wiring + final cleanup *(done)*

**Scope (executed):**

- Verified pytest-device's empty-registry path through `_pick_single_device` / `_load_fallback_device`: `resolve_ide_devices` returns an empty list when `defaults.{micropython,circuitpython}` are null and no devices are registered, and the plugin already routes that to a `pytest.skip` (line 1098).  The two skip messages updated to point users at the unified `add-device` flow:
  - "No devices.yml found" → suggests running `setup` then `add-device <id> --address <port>` via the workspace's `run.py`.
  - "No devices configured" → suggests running `add-device <id> --address <port>` (probes hardware identity + fills in defaults on first registration).
  - Both messages stay neutral about the entry-point command (`python scripts/run.py` in mono-repo vs `python run.py` in the workspace-template) by referring to "your workspace's run.py" rather than pinning a specific path.
- Final docs sweep:
  - `docs/contributing/development-pycharm.md`'s functional-test setup paragraph rewritten to walk through `setup` → `add-device` → fill-in-secrets.yml.
  - `docs/contributing/development-other-editors.md`'s setup paragraph updated to mention the workbench-owned starters + `add-device` flow.
  - `plans/next-up.md`'s parked CI-device-testing line updated to reference `secrets.yml` (the post-Phase-3 shape) instead of the never-existed `device-config.yml`.
  - Frozen historical entries in `plans/next-up.md` Done (line 167 etc.) intentionally left referencing the old `device-config.yml` name — they describe what was true at the time.
- This workstream's entry in `plans/next-up.md` moved from "Now" to "Done."

**Files touched (this phase):** 4.

---

## Cross-cutting design questions (ask user before phase start)

1. **Phase 1: `add-device` UX in mono-repo** — Should `python scripts/run.py setup` automatically prompt "register a board now? [y/N]" or just print a hint and exit?  Auto-prompt is friendlier; print-and-exit is less surprising.  *Lean: print-and-exit (interactive prompts in setup scripts age poorly in CI).*

2. **Phase 2: manifest format** — `[tool.chumicro.config]` in `pyproject.toml` (discoverable via existing `pip show` etc.) vs separate `chumicro_config.toml` per library (easier to read at a glance, doesn't bloat pyproject).  *Lean: pyproject — pyproject is already the canonical metadata location; introducing a parallel file adds discovery cost.*

3. **Phase 3: secrets.yml format** — flat `key: value` (matches template repo) vs nested `[wifi]\npassword = "..."` (matches the merged config shape).  *Lean: flat — matches template repo, simpler resolver semantics, the `!secret <name>` indirection is the only moving part.*

4. **Phase 4: per-library vs per-test-file `config.toml`** — A library has multiple test files (e.g., `test_real_basic.py`, `test_real_advanced.py`).  Per-library config.toml is simpler; per-test-file handles the rare divergent case but adds N×M files.  *Lean: per-library, with per-test-file as escape hatch (file naming: `config_<test_name>.toml` if needed).*

5. **Phase 4: gradual migration vs flag day** — Opt-in flag means dual-path (`_test_creds` + `load_runtime_config`) coexist for some commits.  Flag day means one big commit migrates all libraries simultaneously.  *Lean: opt-in for the plumbing (`bake_runtime_config` flag), per-library flag-day for the conftests (each library migrates atomically) — bounded blast radius per commit.*

6. **Phase 4: how does `chumicro-pytest-device` find the per-library `config.toml`?** — Convention: `functional_tests/config.toml` relative to the test file, walking up to the nearest workspace.yml.  Or: explicit hint via pytest fixture / collect hook.  *Lean: convention — matches how `chumicro_workspace` already discovers projects relative to workspace.yml.*

---

## Pre-conditions for a fresh agent picking this up

A fresh agent picking up this workstream cold should:

1. Read this file end-to-end.
2. Read [`plans/now.md`](../../next-up.md) for the current snapshot.
3. Read [`plans/decisions/0030-config-and-state.md`](../../decisions/0030-config-and-state.md), [`plans/decisions/0035-runtime-config-structure.md`](../../decisions/0035-SUPERSEDED-BY-0036-runtime-config-structure.md), [`plans/decisions/0036-chumicro-config-library.md`](../../decisions/0036-chumicro-config-library.md).
4. Skim the workspace-template repo's [`workspace.yml`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/workspace.yml), [`projects/_template/config.toml`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/projects/_template/config.toml), and [`_workspace_template/devices.yml`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/_workspace_template/devices.yml) to internalize the target shapes.
5. Check whether the ADR-cleanup agent's work has landed.  If yes, promote the embedded ADR section above into `plans/decisions/NNNN-config-pipeline-unification.md` (next available number) and update its status to `accepted`.
6. Pick up the next unstarted phase.  Phases must be done in order — Phase 4 specifically depends on Phase 2's manifests + Phase 3's `workspace.yml` to deliver useful validation messages.

## Constraints

- Nothing has been published to PyPI yet; no backward-compatibility burden on file formats or CLI flags.
- The workspace-template repo must keep working throughout — every change either improves or is a no-op for that repo.  Verify after each phase.
- Coverage gate stays at 94% per Decision 0025.
- AGENTS.md non-negotiables apply (no `__future__` in libraries/, absolute imports in device code, etc.).
