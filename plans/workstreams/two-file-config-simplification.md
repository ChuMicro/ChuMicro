# Two-file config simplification — collapse Decision 0057's 4-layer overlay to 2 gitignored files

Status: `planned` (not yet executed)
Filed: 2026-05-04 (during the same session that shipped Decision 0057)
Predecessor: [Decision 0057](../decisions/0057-drop-secret-marker.md) shipped a 4-layer overlay design.  This workstream walks that back to the 2-file design the user originally wanted.  The user accepted the plan ("plan and then go") in good faith but the plan I proposed had four layers when their actual ask was two; we both missed it until the implementation made the over-engineering visible.

## Goal

Replace Decision 0057's 4-layer overlay (committed `workspace.yml` → gitignored `workspace.local.yml` → committed `config.toml` → gitignored `config.local.<suffix>`) with a 2-layer design where both files are gitignored.

## Final design

Two files, both gitignored, both materialized from a starter on first `setup`:

| Layer | Tracked | Purpose |
|---|---|---|
| `workspace.yml` | **gitignored**, materialized by `setup` from a workbench-owned starter (`chumicro_workspace.read_workspace_yml_starter`) | Workspace-wide defaults *and* credentials in one place.  Contributor / user fills in real values; never committed. |
| `projects/<name>/config.toml` | **gitignored** when scaffolded by `python run.py new`.  Tracked when shipped with the workspace template repo (`projects/_template/`, `projects/example_sensor/`, `examples/*`) — gitignore patterns don't untrack already-tracked files. | Per-project knobs.  User-authored projects keep their config.toml private; example/scaffold copies that ship with the template stay tracked. |

Pipeline: deep-merge two layers — `workspace.yml` defaults → `projects/<name>/config.toml`.  No `workspace.local.yml`.  No `config.local.<suffix>`.  No marker.  No resolver.

The marker (`!secret <name>`) existed precisely to bridge "committed-shape" and "uncommitted-values".  When *both* files are gitignored, there is no committed→gitignored bridge to span; the bridge disappears and so does its mechanism.

### Why this beats Decision 0057's shape

0057 kept `workspace.yml` committed to preserve "schema as documentation" — the idea being a fresh clone reads the committed `workspace.yml` and learns what shape the defaults take.  Two problems:

1. **The split was already paying the same cost the marker had paid.**  With 0057's design, a contributor still edits *two* files for one logical thing: their wifi network.  SSID + non-credential overrides go in committed `workspace.yml`, password goes in gitignored `workspace.local.yml`.  Same friction as `secrets.yml` + `!secret` markers, just with structural deep-merge instead of a marker.
2. **Schema-as-documentation is better served by the starter.**  The workbench-owned starter (`workspace_yml_starter`) carries the schema with commented examples.  A fresh clone runs `setup`, gets a materialized `workspace.yml` with the schema visible inline, and edits it.  That's the same documentation benefit without the file-split cost.

The `config.local.<suffix>` per-project credential override that 0057 introduced was solving a hypothetical future need ("a user with two wifi networks across projects").  Drop it — YAGNI.  If the case becomes real, address it then with whatever's simplest at that point.

## What changes from the 0057 shipped state

### Workspace package (`workbench/workspace/`)

Source code:

- `pipeline.py` — drop `workspace_local_yaml=` and the `config.local.<suffix>` auto-discovery from `compose_runtime_config` and `build_runtime_config`; merge becomes `workspace_yaml` defaults → `project_config` only.
- `loaders.py` — `read_workspace_yaml` no longer needs to special-case "missing file returns empty dict" (that was added for the optional overlay).  Restore the `FileNotFoundError` shape on missing primary `workspace.yml`.
- `secrets.py` — already deleted in 0057.  Stays deleted.
- `workspace_local_yml_starter.py` → rename to `workspace_yml_starter.py`.  Public reader: `read_workspace_local_yml_starter` → `read_workspace_yml_starter`.
- `_payloads/workspace_local_yml/starter.yml.template` → rename to `_payloads/workspace_yml/starter.yml.template`.  Content rewritten as a *complete* `workspace.yml` (workspace-wide defaults + commented credential examples) instead of a "deep-merge overlay" snippet.
- `workspace.py` — drop `WorkspaceLayout.workspace_local_yaml` property; `WorkspaceLayout.workspace_yaml` stays.
- `boot_shim.py` / `deploy_source.py` / `import_graph.py` / `cli.py` — drop `workspace_local_yaml=` parameter from every signature.  Same `WithRuntimeConfig` constructor signature drops it.
- `health.py` — drop `check_workspace_local_yaml`; `collect_health_findings` returns to 4 checks (workspace.yml / devices.yml / projects / python-version moved into doctor).
- `recovery.py` — `missing-config-key` hint loses the `workspace.local.yml` mention.
- `template_apply.py` — `_WORKBENCH_STARTERS` ships `workspace.yml` (from `read_workspace_yml_starter`) instead of `workspace.local.yml`.
- `template_zones.py` — `workspace.yml` stays USER_OWNED.  `workspace.local.yml` entry deleted.
- `__init__.py` — drop `read_workspace_local_yml_starter` export; add `read_workspace_yml_starter`.
- `VERSION` — bump 0.8.0 → 0.9.0 (another breaking API change: `workspace_local_yaml=` kwargs gone, starter reader renamed).

Tests:

- `test_pipeline.py` — drop the `_workspace_local_yaml_path` test, drop the `config.local` overlay test, drop the "default local yaml path" test.  Restore the simpler 2-layer shape.
- `test_loaders.py` — drop the "missing file returns empty" branch on `read_workspace_yaml`.
- `test_workspace_local_yml_starter.py` → rename to `test_workspace_yml_starter.py`.  Reshape content to assert on the full-workspace.yml starter (not the overlay starter).
- `test_health.py` — drop `TestCheckWorkspaceLocalYaml`; `TestCollectHealthFindings` expects the 4-row shape (no WORKSPACE.LOCAL.YML).
- `test_workspace.py` — drop the `workspace_local_yaml` property assertion.
- `test_template_zones.py` — drop the `workspace.local.yml` cases.
- `test_template_apply.py` — drop the `workspace_local_yml` references; the workbench-starter test asserts on the materialized `workspace.yml` shape.
- `test_boot_shim.py` / `test_deploy_source.py` / `test_import_graph.py` / `test_cli.py` — drop `(tmp_path / "workspace.local.yml").write_text(...)` setups; drop `workspace_local_yaml=` kwargs in all `project_*_source` / `WithRuntimeConfig` callsites.
- `test_recovery.py` — `missing-config-key` hint test gets the new wording (no `workspace.local.yml` reference).

### Mono-repo top level

- `git rm workspace.yml` — the previously-committed file gets removed.  Contributors who pull this commit re-run `setup` to get a materialized version.
- New: `_workspace_template/workspace.yml` carrying the mono-repo's specific opinions (wifi.ssid placeholder, mqtt broker = `test.mosquitto.org`, etc.).  `materialize_templates` picks this up first; it overrides the workbench's minimal starter for this repo only.
- `.gitignore` — keep `workspace.yml` gitignored (already there from 0057).  Drop `workspace.local.yml`.  Drop `projects/**/config.local.{toml,yml,yaml}` and `libraries/*/functional_tests/config.local.{toml,yml,yaml}` patterns.  Decide whether to keep `secrets.yml` legacy guard (probably drop — 0057 added it as one-cycle defense; second iteration starts to be cruft).
- `scripts/generate_config_files.py` — materialize `workspace.yml` (from `read_workspace_yml_starter`), not `workspace.local.yml`.
- `scripts/tests/test_generate_config_files.py` — assertion targets shift from `workspace.local.yml` to `workspace.yml`.
- Functional test conftests: drop `workspace_local_yaml=` / `_WORKSPACE_LOCAL_YAML` references in every `libraries/*/functional_tests/conftest.py`.  Pipeline call becomes `compose_runtime_config(workspace_yaml=…, project_config=…)`.

### Mono-repo docs

- `plans/decisions/0057-drop-secret-marker.md` — rewrite (or supersede with a new ADR).  See "Open question 1" below.
- `plans/decisions/0035-runtime-config-structure.md` §5 — annotation gets simpler: pipeline is 2 layers, both gitignored.
- `plans/decisions/0055-config-pipeline-unification.md` §3 — annotation gets simpler.
- `workbench/workspace/README.md` — config-flow diagram redrawn as 2 layers (1 file → 1 file → msgpack).
- `workbench/workspace/docs/guide.md` — config-flow diagram + `status` / `doctor` labels match the new check set; the `workspace.local.yml` mention in the workspace-layout snippet goes away.
- `docs/contributing/device-testing.md` — section 3 ("Configure workspace.yml + workspace.local.yml") becomes "Configure workspace.yml"; one file, one place.
- `docs/contributing/development-{vscode,pycharm,other-editors}.md` — same one-file message.
- `plans/next-up.md` — close out the Phase 4.5a follow-on; pointer at the new ADR.

### Workspace template repo (`ChuMicro-Workspace-Template`)

- `git rm workspace.yml` — drop the tracked file from the template.  `setup` materializes it from the workbench starter.
- `.gitignore` — drop `/workspace.local.yml`, drop the `projects/**/config.local.<suffix>` patterns, drop the `secrets.yml` legacy guard if mono-repo also drops it.  Add `/projects/**/config.toml` to gitignore user-scaffolded project configs (the tracked `_template/`, `example_sensor/`, `examples/*` configs stay tracked because gitignore doesn't untrack).
- `README.md` — describe the 2-file ecosystem; drop the `workspace.local.yml` walkthrough; the credential-entry step lives in `workspace.yml` directly.
- `AGENTS.md` + `CONTRIBUTING.md` — same vocabulary swap.
- `.github/skills/add-new-thing/SKILL.md` — wire-credentials step rewritten for the 2-file shape (set `defaults.wifi.password` directly in the gitignored `workspace.yml`).
- `pyproject.toml` — bump `chumicro-workspace` floor 0.8.0 → 0.9.0.

## Migration impact

Three workspace shapes now exist in the wild:

1. Pre-0057 — committed `workspace.yml` + committed `config.toml` + gitignored `secrets.yml` + `!secret` markers.
2. 0057 (currently shipped) — committed `workspace.yml` + gitignored `workspace.local.yml` + committed `config.toml` + optional gitignored `config.local.<suffix>`.
3. This workstream's target — gitignored `workspace.yml` + gitignored `projects/*/config.toml`.

Each transition is a hard break (no compat shim); the migration in each direction is manual.  Both repos are sole-developer at the time of this workstream, so the no-shim trade-off is acceptable.  Contributors / users who clone post-this-workstream see only design 3 — they never encounter 1 or 2.

The breaking-change story to spell out in the new ADR:

- **From design 1 (pre-0057)**: Drop every `!secret` reference.  Move everything from the gitignored `secrets.yml` into the gitignored `workspace.yml` under section-namespaced paths (`wifi_password: foo` → `defaults: { wifi: { password: foo } }`).  Run `git rm --cached workspace.yml` if the file was tracked previously — gitignore doesn't untrack what's already tracked.
- **From design 2 (0057's shipped state)**: Move everything from `workspace.local.yml` into `workspace.yml` (same shape; just collapse the two files).  Run `git rm --cached workspace.yml` to make the previously-tracked file private.  Delete `workspace.local.yml`.

## Open questions

1. **Rewrite Decision 0057 in place, or supersede with a new ADR (0058)?**  Argument for supersede: 0057 shipped one day before this rewrite; a clean "we walked back the walk-back" record is more honest to the design history than a rewrite that erases what landed.  Argument for in-place: the *underlying* decision (drop the marker) is unchanged; only the layering shape walks back.  Lean: supersede with 0058; keep 0057 in the record marked as superseded.
2. **Where does the mono-repo's mqtt broker default live?**  Options: (a) `_workspace_template/workspace.yml` in the mono-repo (mono-repo customizes the workbench starter for its own contributors); (b) workbench's starter ships it generically (but then every fresh user workspace also gets `test.mosquitto.org` as a default, which may confuse fresh users with no MQTT story).  Lean: (a) — the mono-repo is special; workspace template users shouldn't inherit the mqtt default.
3. **`secrets.yml` in `.gitignore` — keep as legacy guard for one more cycle, or drop?**  0057 added it as a one-cycle defense.  Keeping it through this workstream means the .gitignore accretes one more line that exists only for migration safety.  Lean: drop now, since contributors who survived the 0057 cycle have already migrated.
4. **The mono-repo currently has no `_workspace_template/` directory.**  This workstream creates one to carry the mono-repo's specific `workspace.yml` defaults (mqtt broker, wifi.ssid placeholder).  Question: should other mono-repo customizations also move into `_workspace_template/`?  Probably no — keep the directory minimal and single-purpose for now.
5. **Nested project configs.**  The workspace template repo's gitignore for user-scaffolded project configs needs `/projects/**/config.toml` (not just `/projects/*/config.toml`) to handle nested project layouts (`projects/garage/sensors/door_open/config.toml`).

## Execution checklist (when the session that picks this up begins)

A future session can use this as a step-by-step.  Phases are independent enough to commit separately.

1. Workspace package source code rewrite (signatures, drops, renames).
2. Workspace package tests update.
3. `chumicro-workspace` VERSION bump 0.8.0 → 0.9.0.
4. Mono-repo top-level changes: `git rm workspace.yml`, create `_workspace_template/workspace.yml`, update `.gitignore`, update `scripts/generate_config_files.py` and its tests, update functional-test conftests.
5. Mono-repo docs: new ADR (0058 superseding 0057, or rewritten 0057), revisions to 0035 / 0055 annotations, README / guide / contributing-docs updates.
6. `python scripts/run.py preflight --coverage-threshold 94` — must pass.
7. Mono-repo commit + push.
8. Workspace template repo: `git rm workspace.yml`, update `.gitignore`, update README / AGENTS / CONTRIBUTING / skills / pyproject (chumicro-workspace>=0.9.0).
9. Workspace template repo: `pytest tests/` — must pass.
10. Workspace template repo commit + push.

## Lessons (from how 0057 went sideways)

- The plan I proposed had a 4-row table early in the session; the user said "plan and then go".  Reading the table inline is easier than counting rows when you skim, and the file count didn't register until the implementation made the four files visible.  When proposing a design with a layer count, **call the count out explicitly** in the prose so the reader has to actively decide they're OK with it.
- The "schema-as-documentation" benefit I leaned on to keep `workspace.yml` committed is delivered just as well by the starter.  A starter file *is* documentation; it's just delivered at materialize time instead of clone time.  If the only argument for committing a file is "so a fresh clone can read the schema", the starter does the same job without the file-split cost.
- "Per-project credential override" (`config.local.<suffix>`) was a hypothetical I designed for and the user never asked about.  When the rationale for a feature is "I'm imagining someone might want this someday", drop it.  YAGNI.
