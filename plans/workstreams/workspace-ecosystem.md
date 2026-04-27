# Workstream: Workspace ecosystem completion

Status: `planned` — drafted 2026-04-27 as the next-session entry point after the workspace-template testing-infrastructure audit closed.  No code shipped under this workstream yet.

## Premise

Project-workspace's eight phases shipped (`plans/workstreams/project-workspace.md`).  The user-facing surface — `chumicro-workspace` CLI, `ChuMicro-Workspace-Template` repo, the eight chumicro libraries — is feature-complete enough to deploy a working sensor thing.  But the experience between **clone the template** and **deploy a working sensor thing** has rough edges:

* Things layout is flat-only — no namespacing, no examples folder.
* No worked examples beyond `things/example_sensor/`.
* No `status` / `doctor` / `deploy --dry-run` / `deploy --watch` quality-of-life commands.
* `workspace.yml`'s `lint` / `coverage_threshold` / `agent_strictness` knobs documented but not wired up.
* `scripts/new_library_scaffold.py` is a mono-repo-only contributor tool that logically belongs in `chumicro-workspace`.
* Documentation across both the chumicro mono-repo and the template repo has drifted in places — never audited as a single pass.

This workstream coordinates the remaining work to bring the ecosystem from "feature-complete" to "user-friendly for beginners and advanced users."

## Pre-conditions for the new session

A fresh agent picking this up cold should:

1. Read this file end to end.
2. Read `plans/now.md` for the current snapshot.
3. Read `plans/workstreams/project-workspace.md` (closed) to understand what shipped.
4. Read `plans/workstreams/nested-things-and-examples.md` (the detailed plan for Phase 1).
5. **Important constraint:** nothing has been published to PyPI yet.  No backward-compatibility burden.  The plan can change file formats, CLI flags, on-device shim layouts, etc. without migration paths.

## Phase list

Each phase is independent enough to ship on its own.  Sequencing reflects priority — earlier phases unblock more downstream work.

### Phase 1 — Nested things + examples folder

**Detail:** [`plans/workstreams/nested-things-and-examples.md`](nested-things-and-examples.md).

Replace the flat `things/<name>/` layout with a nested-namespace tree (`things/upstairs/bedroom_sensor/`, `things/garage/sensors/door_open/`, etc.) and add an `examples/` folder of multi-thing demos to the template repo.  The two are coupled because the most natural example (`examples/two_things/{server,sensor}/`) is itself a nested layout.

Touches both repos: chumicro mono-repo (deploy machinery, boot shim, CLI) and the template repo (examples content, README updates).

Estimated scope: ~600 LOC across 8 files in the mono-repo + ~10 new files in the template repo.  Probably 2-3 sessions to land cleanly with task-checkpoint commits per slice.

### Phase 2 — Workspace ergonomics quick wins

Four small commands, each ~50–200 LOC.  Independent — can land in any order.

#### 2a — `python run.py status`

Reports workspace health at a glance.  Output:

```
$ python run.py status

WORKSPACE        my-workspace at /Users/chux/projects/my-house
WORKSPACE.YML    ✓ valid
DEVICES.YML      ✓ 3 devices registered, 2 reachable
SECRETS.YML      ⚠ wifi_password still 'replace-me' — edit before deploying
THINGS           4 things  (upstairs/bedroom_sensor, garage/sensors/door_open, …)
LAST DEPLOY      garage/sensors/door_open → back-porch (2 min ago)
ACTIVE THING     back-porch: garage/sensors/door_open
                 greenhouse: (no active thing — not yet deployed)
```

Reads workspace.yml, devices.yml, secrets.yml, walks `things/`, optionally probes `/active.py` on each registered device (with `--no-probe` to skip).  Each row has its own check function that returns a (status, hint) tuple.  Output is colour-coded green / yellow / red.

Touches: `chumicro_workspace/cli.py` (new `_cmd_status`), `chumicro_workspace/health.py` (new module).

#### 2b — `python run.py doctor`

Stricter sibling of `status` — runs every health check + remediation hint.  Catches failure modes before deploy:

```
$ python run.py doctor

✓ Python 3.11+ (got 3.14.4)
✓ Workspace structure (workspace.yml, things/, _templates/)
✓ devices.yml schema valid
⚠ secrets.yml has placeholder values:
    wifi_password = 'replace-me'
    HINT: edit secrets.yml before deploying any thing that needs wifi
✗ things/garage/sensors/door_open/app.py has no run() function
    HINT: define `def run():` — the boot shim imports it
✓ Every !secret reference in config.toml resolves against secrets.yml
✗ back-porch unreachable on /dev/cu.usbmodem1101
    HINT: try `python run.py discover` to see currently-attached ports
```

Same scaffolding as `status` plus per-thing AST scan (does `app.py` define `run`?), config-merge dry-run (do all `!secret` references resolve?), and per-device probe-or-fail.

Touches: `chumicro_workspace/cli.py` (new `_cmd_doctor`), `chumicro_workspace/health.py` (extends 2a).

#### 2c — `python run.py deploy --dry-run`

Show what would land where, without writing.  Output:

```
$ python run.py deploy garage/sensors/door_open --dry-run

would deploy garage/sensors/door_open to back-porch (/dev/cu.usbmodem1101) in flash mode

device files (12 total, 38 KiB):
  /code.py                                  (28 B,   shim)
  /active.py                                (95 B,   shim)
  /lib/things/__init__.py                   (0 B,    namespace)
  /lib/things/garage/__init__.py            (0 B,    namespace)
  /lib/things/garage/sensors/__init__.py    (0 B,    namespace)
  /lib/things/garage/sensors/door_open/__init__.py  (0 B)
  /lib/things/garage/sensors/door_open/app.py       (1.8 KiB)
  /lib/chumicro_wifi/__init__.py            (4.2 KiB, library)
  ...
  /runtime_config.msgpack                   (210 B, baked from config.toml + workspace.yml + secrets.yml)
```

Hooks the existing `Deployer.deploy` flow with a no-op transport that records intended writes.  Useful for "did the !secret merge actually flatten?" debugging.

Touches: `chumicro_deploy` (new `DryRunTransport`), `chumicro_workspace/cli.py` (`--dry-run` flag on `_cmd_deploy`).

#### 2d — `python run.py deploy --watch`

File-watcher: re-deploys on save.  Stays in the foreground; `Ctrl-C` exits.

```
$ python run.py deploy garage/sensors/door_open --watch
deploying initial...
deployed in 4.2s
watching things/garage/sensors/door_open/, workspace.yml, secrets.yml
... edit + save app.py ...
detected change: things/garage/sensors/door_open/app.py
deploying...
deployed in 1.8s
```

Uses the stdlib (`os.path.getmtime` polling at 0.5s interval) — avoids pulling `watchdog` as a dep.  Watches the thing dir + workspace-level config files.  Debounces rapid saves (200ms).

Touches: `chumicro_workspace/cli.py` (`--watch` flag on `_cmd_deploy`), `chumicro_workspace/_watch.py` (new tiny module, ~80 LOC).

### Phase 3 — Library scaffolder migration

Move `scripts/new_library_scaffold.py` (208 LOC, mono-repo-only contributor tool that creates `libraries/<name>/`) into `chumicro-workspace` as `python run.py new --library <name>`.  Mirrors the existing `python run.py new <thing>` shape.

Why migrate: scaffolding is a workspace-package concern (Decision 0032 §Rule 8 — scripts consume workbench packages, not the other way around).  An external user developing their own chumicro-style libraries should get the same scaffolder the chumicro mono-repo uses.

Slices:

* **3a** — Carve the templated content out of `scripts/templates/*.template` files into `chumicro-workspace`'s `_payloads/` tree.  Materialise a `chumicro_workspace.scaffold` module with `scaffold_library(target_dir, name)` and `scaffold_thing(target_dir, name)` functions.
* **3b** — Add `--library` flag to `python run.py new`.  Auto-routes: bare name → thing scaffold, `--library` → library scaffold.  Library scaffold writes to `libraries/<name>/` (relative to workspace root) by default; `--into <path>` overrides.
* **3c** — Update `scripts/run.py new-library` to call `chumicro_workspace.scaffold.scaffold_library` instead of the local `scripts/new_library_scaffold.py`.  Delete the local copy + its tests; relocate tests to `workbench/workspace/tests/test_scaffold.py`.

Touches: `workbench/workspace/src/chumicro_workspace/{cli.py,scaffold.py,_payloads/library_template/*}`, `scripts/{new_library_scaffold.py (delete),tests/test_new_library_scaffold.py (delete)}`, `scripts/run.py` (rewire `new-library` task).

Estimated scope: ~250 LOC moved + ~50 LOC adapter glue.  Single session.

### Phase 4 — workspace.yml knobs wired up

The `workspace.yml` design (Decision 0029) includes three quality knobs:

```yaml
quality:
  lint:
    enabled: true
    select: ["E", "F", "I"]
  coverage_threshold: 85
  agent_strictness: relaxed   # or "strict"
```

None of these are wired to anything.  Phase 4 wires them:

* `lint.enabled = false` → `python run.py lint` becomes a no-op with a hint.
* `lint.select` → forwarded to ruff as `--select`.
* `coverage_threshold` → forwarded to pytest's `--cov-fail-under`.
* `agent_strictness = strict` → enables AST-level checks in the test harness (no naked `except:`, no global state in things).  `relaxed` skips those.

Touches: `chumicro_workspace/quality.py` (new), `chumicro_workspace/cli.py` (`_cmd_lint`/`_cmd_test` consult the loaded config), workspace template's `workspace.yml` template (add the example knobs commented out).

Estimated scope: ~150 LOC + tests.

### Phase 5 — Documentation audit

After Phases 1–4 land.  Single review pass across both repos catching anything stale.

Areas to audit:

| Path | What to check |
|---|---|
| `workbench/workspace/docs/guide.md` | Walks the user through the full workflow.  Update for nested things, examples folder, new commands (status/doctor/dry-run/watch). |
| `ChuMicro-Workspace-Template/README.md` | Quickstart + worked example.  Add examples/ section, nested-things tip, new commands. |
| `ChuMicro-Workspace-Template/AGENTS.md` | Commands table + rules of thumb.  Same updates. |
| `ChuMicro-Workspace-Template/CONTRIBUTING.md` | Last touched 2026-04-26 — verify it still matches the post-Phase-1 layout. |
| `libraries/*/README.md` (12 libraries) | Each one separately — most stable, but `chumicro-config` / `chumicro-workspace` install snippets may need refreshing if Phase 3 changes `pip install` paths. |
| `docs/contributing/*.md` (mono-repo) | Likely has stale references to migrated/deleted scripts (`device_config.py`, `pytest_device.py`, etc.). |
| `plans/now.md` + `plans/next-up.md` | Already kept fresh by the task-checkpoint discipline; verify after the audit pass. |
| Decision docs `plans/decisions/00**.md` | Mostly retrospective, but Decision 0029 (project workspace) and Decision 0038 (workspace template) may need addenda for nested layouts. |

Output: a single audit-results commit with every doc edit.  No new content — only freshening / fact-checking / cross-link repair.

Estimated scope: ~10–20 file edits.  Half a session.

### Phase 6 (separate track) — Richer REPL

[`plans/workstreams/repl-playground.md`](repl-playground.md) Phase 1a/b/c.  Independent of Phases 1–5; can run in parallel with another contributor.

* **1a** — line mode + persistent per-device history (~250 LOC)
* **1b** — `:edit` / `:save` / `:load` / `:snippets` (~150 LOC)
* **1c** — tab completion via on-device `dir()` query (~200 LOC)

Detail already drafted in the linked workstream doc.  Not blocked by anything in this workstream; not blocking anything either.

## Out of scope for this workstream

The following appear in `plans/next-up.md` but are intentionally not part of this ecosystem-completion pass:

* **Rebrand ChuMicro → ChipPy** — separate workstream (`plans/workstreams/rename-to-chippy.md`), executes when ready for first public open.
* **OTA** — its own unscoped workstream (`plans/workstreams/ota.md`), waits for "thing on a wall for 30+ days" trigger.
* **Multi-thing-staging cleanup** — flash-budget-driven redesign of `switch`; waits for "build a real second simple thing as a fixture" per the existing next-up entry.
* **`pytest_device` `_test_creds` deploy bridge** — orthogonal infrastructure work; tests skip silently without it.
* **`generate_config_files.py` calling `chumicro_workspace` directly** — one bullet of the migration backlog still open.  Lower priority than Phases 1–5.
* **Per-runtime adapter helper extraction** — waits for third consumer.
* **Expand device test matrix beyond ESP32-S2** — orthogonal hardware work.
* **GitHub Copilot review as PR gate** — defer until community contributions begin.
* **Digital I/O second library seam** — independent library work.
* **Performance / resource benchmarking infrastructure** — independent infrastructure.
* **Slow MP RAM-mode functional test investigation** — independent profiling.

These stay queued in `plans/next-up.md` and get picked up after this workstream closes.

## Sequencing recommendation

```
Phase 1 (nested things + examples)              ← user's directive; biggest win
   └→ Phase 5 (doc audit)                        ← after structural changes settle

Phase 2 (ergonomics) ──┐
Phase 3 (scaffolder) ──┼─→ Phase 5 (doc audit)
Phase 4 (yml knobs)  ──┘

Phase 6 (REPL) — runs in parallel with everything; standalone track
```

Phases 2–4 can land in any order between Phase 1 and Phase 5.  Phase 5 must come last because it's the cleanup pass.

## Acceptance for the workstream as a whole

A user clones [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) and:

1. Runs `python run.py setup` then `python run.py status` to confirm everything's wired.
2. Browses `examples/` to see real worked projects (single-thing + multi-thing).
3. Runs `python run.py new garage/door_open` and gets a nested thing scaffolded.
4. Edits + runs `python run.py deploy garage/door_open --watch` for a fast inner loop.
5. Hits `python run.py doctor` when something goes wrong; gets a precise hint.
6. Reads any of the cross-referenced docs and finds them current.

Plus an advanced user can develop their own chumicro-style libraries with `python run.py new --library mylib` (Phase 3).

## Notes for the executor

* **No backward compatibility.**  Nothing has been published.  Change `THING_NAME` format, CLI flag shapes, file layouts freely if it makes the design cleaner.  Do NOT add migration logic.
* **Two-repo flow.**  Phases 1, 2, 3, 4 each touch the chumicro mono-repo.  Phase 1 + Phase 5 also touch the template repo.  Each phase's commit list should call out which repo each file lives in.
* **Task-checkpoint per slice.**  Every slice ends with a green preflight + commit + push.  Don't batch multiple slices into one commit.
* **Tests come along.**  Every new module gets a test file.  Coverage gate stays at 94 % for changed packages.
* **Templates are under `workbench/workspace/src/chumicro_workspace/_payloads/` not the template repo's `_templates/`.**  The template repo's `_templates/` is a *materialisation source* for `secrets.yml` / `devices.yml`; the *scaffolds* (thing, library) live in the package payload tree so `chumicro-workspace new` can run independently of any template-repo clone.
