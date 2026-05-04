# Workstream: scripts/ ↔ workbench/ ↔ workspace-template config unification

Status: **proposed** (drafted 2026-05-04, awaiting kickoff after ADR-cleanup agent finishes).

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

## Embedded ADR proposal

> **Filing note (2026-05-04):**  An ADR-cleanup agent is currently active.  This proposal is held inline rather than promoted to a numbered ADR until that work lands.  When the cleanup completes, lift this section into `plans/decisions/NNNN-config-pipeline-unification.md` (next available number) and update `## Status` to `accepted`.

### Title

Unify mono-repo and template-repo around shared `devices.yml` (probe-driven) + `workspace.yml + config.toml + secrets.yml` (chumicro-config-baked) flows owned by workbench packages.

### Status

`proposed`

### Date

2026-05-04

### Related decisions

- 0027 — device-testing infrastructure (`devices.yml` schema origin)
- 0029 — project workspace (three-zone shape; workspace-template's source)
- 0030 — config-and-state (host TOML / device msgpack split)
- 0032 — workbench host tools (decides what *can* live in `workbench/`)
- 0035 — runtime-config structure (section-namespaced shape)
- 0036 — `chumicro-config` library (`load_runtime_config` + `load_section`)
- 0044 — deploy-time runtime-file filtering (precedent: workbench-owned filter applied uniformly across every deploy path)
- 0047 — `deploy_mode: flash` default (precedent: shared default flowed via `chumicro-deploy` constant rather than duplicated per-repo template)

### Context

The mono-repo and the workspace-template repo manage the same two artifacts (`devices.yml`, runtime config) with two different file shapes and two different population mechanisms.  The workbench packages already own the primitives that *could* drive both — `chumicro_deploy.config.devices_yaml` for the three-zone probe-aware reader/writer, `chumicro_workspace.pipeline.build_runtime_config` for the workspace-yaml + config.toml + secrets.yml + msgpack pipeline, `chumicro_config.load_runtime_config` for the on-device read.  The mono-repo's functional tests bypass all of this with hand-rolled `tomllib` reads of `chumicro-dev-config.toml` and a materialized `_test_creds.py` import shim.  This is the only consumer of `chumicro-config`-shaped data in the entire ecosystem that doesn't flow through `chumicro-config`.

### Decision

Adopt the workspace-template's flows as the canonical pattern; the mono-repo dogfoods them.  Specifically:

1. **`devices.yml`** — Mono-repo drops the two `sample-*-board` pre-fills.  Initial state matches the template repo's three-zone-headed empty registry.  Population is driven by `chumicro-workspace add-device` (already implemented in `chumicro_deploy.config.devices_yaml.add_device`).  The `ide_runtime` field is part of the unified schema in **both** repos (corrected 2026-05-04 after user pushback) — workspace-template users who scaffold their own libraries via `python run.py new --library <name>` need IDE play-button targeting just like mono-repo contributors.  The schema reader already accepts `ide_runtime`; the workspace-template repo's `_workspace_template/devices.yml` gains the field as a small follow-up after Phase 1's mono-repo work lands.

2. **Library config manifests** — Each library's `pyproject.toml` declares a `[tool.chumicro.config]` section listing the runtime-config sections it reads and their required / optional keys.  The schema is read by `chumicro-workspace deploy` for deploy-time validation (clear error messages instead of cryptic boot-time `MissingConfigKey`) and by README-generation tooling so config docs stay in sync with code.

3. **Mono-repo workspace root config** — Add `workspace.yml` + `secrets.yml.template` at the mono-repo root.  Same shape as the workspace-template's files.  Functional-test creds live in `secrets.yml` (gitignored, edited once per clone, same UX as today's `chumicro-dev-config.toml`); shared defaults (`[defaults.wifi].ssid`, `[defaults.mqtt].broker`, etc.) live in `workspace.yml` (committed, references secrets via `!secret <name>`).

4. **Functional tests dogfood `chumicro-config`** — Each library's `functional_tests/` becomes a thin "project": a `config.toml` (often empty — inherits all defaults from `workspace.yml`) and on-device test code that calls `chumicro_config.load_runtime_config()`.  `chumicro-pytest-device` gains an opt-in flag that bakes a `runtime_config.msgpack` per test session via `chumicro_workspace.pipeline.build_runtime_config()` and stages it onto the device.  The hand-rolled `_test_creds.py` materialization across every networking library's conftest is deleted.  `scripts/templates/chumicro-dev-config.toml.template` is deleted.

5. **What stays divergent** — Mono-repo's CI / preflight / bundle-release scripts (gates, mip validation, runtime preparation, docs deploy) are unaffected — this workstream is config + device-registry only.  Those scripts have no equivalent in the workspace-template repo and shouldn't grow one.

### Consequences

**Positive:**
- Single source of truth for runtime config across the entire ecosystem.  Mono-repo functional tests behave like user projects.  Bug-or-improvement to the config pipeline lands once, benefits both repos.
- Mono-repo gains hardware-identity tracking (catches "wrong board plugged in" silently-wrong-test failures).
- Library config requirements become machine-readable — `chumicro-workspace deploy` can refuse to ship a project that imports `chumicro_wifi` but has no `[wifi]` section, with a precise error.
- `chumicro-config` gets dogfooded by the same humans maintaining it — improvements driven by daily use, not by hypothetical user reports.

**Negative:**
- One-time migration cost across five-plus library `functional_tests/conftest.py` files.  Estimated ~300 LOC deleted, ~150 LOC added (the conftest cleanup is net-negative; the new `workspace.yml` + per-library `config.toml` files are small).
- Contributors must learn the `add-device` flow.  Mitigated by the three-zone header comments + a one-time prompt in `python scripts/run.py setup`.
- Per-library `functional_tests/config.toml` files will exist even when often empty.  Tradeoff against the alternative (ad-hoc divergence between libraries).

**Neutral:**
- ABI / API: no library or workbench package's *public* surface changes.  All movement is in mono-repo internals + new opt-in flag on `chumicro-pytest-device`.

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

**Workspace-template half (small follow-up after this phase lands):**
- Add `ide_runtime: micropython` to `_workspace_template/devices.yml`'s `defaults:` block so workspace-template users who scaffold their own libraries get the same IDE play-button targeting as mono-repo contributors.  Fully additive — schema reader already accepts the field.

**Files touched (mono-repo):** ~6.  Estimated 1 session.

### Phase 2 — library config manifests

**Scope:**
- Add `[tool.chumicro.config]` to each of the 8 networking-or-config-touching libraries' `pyproject.toml` files: `wifi`, `requests`, `http_server`, `mqtt`, `sockets`, `websockets` (if it has one), `ntp`, plus any other library that calls `load_section`.  The schema:
  ```toml
  [tool.chumicro.config]
  sections = ["wifi"]

  [tool.chumicro.config.sections.wifi]
  required = ["ssid", "password"]
  optional = ["hostname"]
  ```
- New `chumicro_workspace.config_manifest` module: reads manifests via `tomllib` from the import-graph of a project; aggregates required / optional keys.
- Wire `chumicro-workspace deploy` to validate project `config.toml` (after merge + secrets resolve, before msgpack write) against the union manifest.  Missing required key → `ConfigManifestError` with precise message.
- Tests: golden-files for manifest aggregation; deploy-time validation pass / fail cases.

**Files touched:** ~8 pyproject.toml files + 1 new module + 1 new test file.  Estimated 1-2 sessions.

### Phase 3 — mono-repo workspace root config

**Scope:**
- Create `workspace.yml` at mono-repo root.  Body mirrors template repo's shape: `defaults.wifi.{ssid, password (with `!secret`)}`, `defaults.mqtt.{broker, port}`, optional `defaults.quality.*`.
- Create `scripts/templates/secrets.yml.template` (gitignored target, generated once at setup).
- `python scripts/run.py setup` materializes both files on first clone.
- Add `workspace.yml` + `secrets.yml` to `.gitignore` patterns (workspace.yml shouldn't be — it's committed; only `secrets.yml`).
- Document the migration: contributors with an existing `chumicro-dev-config.toml` get a one-time message pointing them at the new shape.

**Files touched:** ~5.  Estimated 1 session.

### Phase 4 — functional tests dogfood `chumicro-config`

**Scope (the biggest phase):**
- Add a `bake_runtime_config: bool = False` opt-in flag (or pytest CLI option `--chumicro-bake-config`) to `chumicro-pytest-device`.  When on, before staging test sources to a device, the plugin:
  1. Locates the workspace root + project context for each test (default: per-library `functional_tests/` directory acts as a "project")
  2. Calls `chumicro_workspace.pipeline.build_runtime_config()` — same path the user-facing `chumicro-workspace deploy` uses
  3. Stages the resulting `runtime_config.msgpack` alongside the test files
- Per-library `functional_tests/config.toml` files (often empty — inherits everything from `workspace.yml` defaults).  `mqtt` will have a `[mqtt.broker]` override if appropriate.
- Rewrite each conftest.py (`libraries/{wifi,requests,mqtt,sockets,http_server}/functional_tests/conftest.py`) to remove the `_test_creds.py` materialization.  Test functions instead call `from chumicro_config import load_runtime_config; config = load_runtime_config()` and read sections directly.
- Delete `scripts/templates/chumicro-dev-config.toml.template`.
- Delete the `_test_creds.py` materialization fixtures.
- Update `docs/contributing/style-guide.md` with the new pattern.

**Files touched:** ~15 (5+ conftests, plugin, several test files, docs, deletions).  Estimated 2-3 sessions.

### Phase 5 — IDE wiring + final cleanup

**Scope:**
- Verify pytest-device IDE play button still resolves devices correctly with the new empty-defaults-until-first-add-device shape (`defaults.{micropython,circuitpython}: null` until populated).  May need a polite "no devices registered yet — run `add-device` first" hint.
- Documentation pass: README, AGENTS, CONTRIBUTING, every `docs/contributing/*.md` references the new flow.
- Move resolved entry into `plans/next-up.md` Done.

**Files touched:** ~5.  Estimated 1 session.

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
2. Read [`plans/now.md`](../now.md) for the current snapshot.
3. Read [`plans/decisions/0030-config-and-state.md`](../decisions/0030-config-and-state.md), [`plans/decisions/0035-runtime-config-structure.md`](../decisions/0035-runtime-config-structure.md), [`plans/decisions/0036-chumicro-config-library.md`](../decisions/0036-chumicro-config-library.md).
4. Skim the workspace-template repo's [`workspace.yml`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/workspace.yml), [`projects/_template/config.toml`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/projects/_template/config.toml), and [`_workspace_template/devices.yml`](https://github.com/ChuMicro/ChuMicro-Workspace-Template/blob/main/_workspace_template/devices.yml) to internalize the target shapes.
5. Check whether the ADR-cleanup agent's work has landed.  If yes, promote the embedded ADR section above into `plans/decisions/NNNN-config-pipeline-unification.md` (next available number) and update its status to `accepted`.
6. Pick up the next unstarted phase.  Phases must be done in order — Phase 4 specifically depends on Phase 2's manifests + Phase 3's `workspace.yml` to deliver useful validation messages.

## Constraints

- Nothing has been published to PyPI yet; no backward-compatibility burden on file formats or CLI flags.
- The workspace-template repo must keep working throughout — every change either improves or is a no-op for that repo.  Verify after each phase.
- Coverage gate stays at 94% per Decision 0025.
- AGENTS.md non-negotiables apply (no `__future__` in libraries/, absolute imports in device code, etc.).
