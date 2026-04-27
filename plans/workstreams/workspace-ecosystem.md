# Workstream: Workspace ecosystem completion

Status: `planned` — drafted 2026-04-27, revised 2026-04-27 with user triage.  Next-session entry point.  No code shipped under this workstream yet.

## Premise

Project-workspace's eight phases shipped (`plans/workstreams/project-workspace.md`).  The user-facing surface — `chumicro-workspace` CLI, `ChuMicro-Workspace-Template` repo, the eight chumicro libraries — is feature-complete enough to deploy a working sensor thing.  But the experience between **clone the template** and **deploy a working sensor thing** has rough edges:

* Things layout is flat-only — no namespacing, no examples folder.
* No worked examples beyond `things/example_sensor/`.
* No `status` / `doctor` / `deploy --dry-run` quality-of-life commands.
* No app-level error recovery hints — raw tracebacks only.
* `workspace.yml`'s quality knobs (lint / coverage / agent_strictness) documented but not wired up.
* No environment layering — single config set for dev / staging / prod.
* `scripts/new_library_scaffold.py` is a mono-repo-only contributor tool that logically belongs in `chumicro-workspace`.
* The `switch` command is a vestige of the soon-to-be-deprecated multi-thing-staging path; with no backward-compat burden, drop it.
* Documentation across both repos has drifted in places — never audited as a single pass.

This workstream coordinates the remaining work to bring the ecosystem from "feature-complete" to "user-friendly for beginners and advanced users."

## Pre-conditions for the new session

A fresh agent picking this up cold should:

1. Read this file end to end.
2. Read `plans/now.md` for the current snapshot.
3. Read `plans/workstreams/project-workspace.md` (closed) to understand what shipped.
4. Read `plans/workstreams/nested-things-and-examples.md` (Phase 1 detail).
5. **Constraint:** nothing has been published to PyPI yet.  No backward-compatibility burden.  Change file formats, CLI flags, on-device shim layouts, and remove-and-replace commands freely.

## Phase list (revised after user triage 2026-04-27)

### Phase 1 — Nested things + examples folder (+ drop `switch`)

**Detail:** [`plans/workstreams/nested-things-and-examples.md`](nested-things-and-examples.md).

Replace flat `things/<name>/` with a nested-namespace tree, add an `examples/` folder of multi-thing demos, and drop the `switch` command since deploy is being reworked anyway.  Slice list (per the detail doc):

* Slice 1 — Recursive thing detection
* Slice 2 — Deploy + boot-shim handle nesting
* Slice 3 — `new` accepts paths + `--from <example>` flag
* Slice 4 — `things` tree renderer + path-aware `rename`
* Slice 5 — `examples/` folder shipped
* Slice 6 — Tests, docs, polish
* Slice 7 — **Drop the `switch` command** (added 2026-04-27 after user triage)

Estimated scope: ~600 LOC across 8 files in the mono-repo + ~10 new files in the template repo.  2-3 sessions.

### Phase 2 — Ergonomics quick wins (six small commands)

Each independent, ships in any order.  Per-command estimates ~50–200 LOC.  Batch as one Phase or split per session — whichever's cleaner at the time.

#### 2a — `python run.py status`

Reports workspace health at a glance.

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

Touches: `chumicro_workspace/cli.py` (new `_cmd_status`), new `chumicro_workspace/health.py` module.

#### 2b — `python run.py doctor`

Stricter sibling of `status` — runs every health check + remediation hint.

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

Same scaffolding as 2a + per-thing AST scan (does `app.py` define `run`?), config-merge dry-run (do all `!secret` references resolve?), and per-device probe-or-fail.

#### 2c — `python run.py deploy --dry-run`

Show what would land where, without writing.  **Doubles as documentation** — `--dry-run` output is the canonical "what does deploy actually do" reference.

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

Useful for "did the !secret merge actually flatten?" debugging too.  Doc-piece deliverable: link the `--dry-run` walkthrough from the workspace template's `README.md` and the chumicro-workspace `docs/guide.md`.

Touches: `chumicro_deploy` (new `DryRunTransport`), `chumicro_workspace/cli.py` (`--dry-run` flag), docs (the documentation piece).

#### 2d — App-level error recovery hints

Today's deploy surfaces raw tracebacks when the thing's own code fails.  No coaching ("did you mean to import …", "your config has an undefined `!secret` reference").  The `chumicro-deploy` recovery layer does this for *transport* failures; nothing does it for *app-level* failures.

Pattern detector + hint table:

| Detected pattern | Hint shown |
|---|---|
| `NameError: name 'foo' is not defined` | `did you forget to import? Common imports: …` |
| `KeyError: 'wifi'` in config-merge | `your thing's config.toml or workspace.yml has no [wifi] section` |
| `ValueError` mentioning `!secret` | `secrets.yml has no entry for that name — did you forget to fill it in?` |
| `OSError: [Errno 2] /runtime_config.msgpack` | `RAM-mode deploy doesn't persist runtime_config — switch to flash mode for things that read config` |
| `ImportError: no module named chumicro_*` | `library not installed in this venv — run `python run.py setup` to refresh deps` |

Hits both stdlib pattern matching and known runtime errors.  ~150 LOC + a hint table that's easy to extend.

Touches: `chumicro_workspace/recovery.py` (new), `chumicro_workspace/cli.py::_cmd_deploy` (run hint pass on failed deploy), `chumicro_deploy/recovery.py` (extend the existing pattern-match table if needed).

#### 2e — `python run.py repl --tail <thing>` auto-deploys before tailing

Today: `python run.py deploy <thing> && python run.py repl --tail`.  Two commands.  Combine: `repl --tail <thing>` deploys then tails.

```bash
python run.py repl --tail garage/sensors/door_open
# deploys, then streams the next 30 s of REPL output, exits clean
```

Falls back to the existing tail behaviour when no positional thing is given.  Tiny addition (~30 LOC) on top of existing `_cmd_repl`.

#### 2f — Multi-device deploys

`python run.py deploy thing1 --to board-a` plus mapping config.  Today: separate invocations per device.

**Scope assessment first.**  If the work is a thin orchestration loop over per-device deploys (~100 LOC), ship it in this Phase.  If it requires reshaping the deploy pipeline to accept multiple targets cleanly, defer it alongside `deploy --watch` (rainy-day).

Decision rule: write a one-paragraph design sketch as the first step of 2f.  If the sketch fits on a sticky note and the implementation is mostly looping, ship.  Otherwise file as a follow-on and move on.

### Phase 3 — Per-environment deploys

User flagged: implement before it gets hard.  Layering env-specific overrides retroactively is invasive once the deploy pipeline matures; ship the seam now while it's simple.

`workspace.yml` gains an `environments:` block:

```yaml
defaults:
  app_marker_prefix: my-house

environments:
  dev:
    mqtt:
      broker: localhost
  staging:
    mqtt:
      broker: staging-broker.example.com
  prod:
    mqtt:
      broker: prod-broker.example.com
```

CLI:

```bash
python run.py deploy garage/sensors/door_open --env prod
python run.py use prod          # set the active env in workspace state
python run.py env               # list envs + show active
```

The existing stub `_cmd_env` / `_cmd_use` get real implementations.  Active-env state lives in a gitignored `~/.chumicro/<workspace-name>/active-env` file (per-user, per-workspace; not in workspace.yml so it doesn't pollute git diffs).

Merge order: `defaults` (lowest) ← `environments.<active>` ← `things/<name>/config.toml` ← `secrets.yml` (`!secret` resolution; highest).

Estimated scope: ~250 LOC.  Touches `chumicro_workspace/{cli.py,merge.py,environments.py (new)}`, plus tests + a doc note.

### Phase 4 — Library scaffolder migration

Move `scripts/new_library_scaffold.py` (208 LOC, mono-repo-only contributor tool that creates `libraries/<name>/`) into `chumicro-workspace` as `python run.py new --library <name>`.  Mirrors the existing `python run.py new <thing>` shape.

Why migrate: scaffolding is a workspace-package concern (Decision 0032 §Rule 8 — scripts consume workbench packages, not the other way around).  An external user developing their own chumicro-style libraries should get the same scaffolder the chumicro mono-repo uses.

Slices:

* **4a** — Carve templated content out of `scripts/templates/*.template` files into `chumicro-workspace`'s `_payloads/` tree.  Materialise a `chumicro_workspace.scaffold` module with `scaffold_library(target_dir, name)` and `scaffold_thing(target_dir, name)` functions.
* **4b** — Add `--library` flag to `python run.py new`.  Library scaffold writes to `libraries/<name>/` (relative to workspace root) by default; `--into <path>` overrides.
* **4c** — Update `scripts/run.py new-library` to call `chumicro_workspace.scaffold.scaffold_library` instead of the local copy.  Delete the local copy + its tests; relocate tests to `workbench/workspace/tests/test_scaffold.py`.

Estimated scope: ~250 LOC moved + ~50 LOC adapter glue.  Single session.

### Phase 5 — Wire `workspace.yml` quality knobs

The `workspace.yml` design (Decision 0029) includes three quality knobs that aren't wired to anything today:

```yaml
quality:
  lint:
    enabled: true
    select: ["E", "F", "I"]
  coverage_threshold: 85
  agent_strictness: relaxed   # or "strict"
```

* `lint.enabled = false` → `python run.py lint` becomes a no-op with a hint.
* `lint.select` → forwarded to ruff as `--select`.
* `coverage_threshold` → forwarded to pytest's `--cov-fail-under`.
* `agent_strictness = strict` → enables AST-level checks (no naked `except:`, no global state in things).  `relaxed` skips them.

Touches: `chumicro_workspace/quality.py` (new), `chumicro_workspace/cli.py` (`_cmd_lint` / `_cmd_test` consult the loaded config), workspace template's `workspace.yml` (add the example knobs commented out).

Estimated scope: ~150 LOC + tests.

### Phase 6 — Documentation audit

After Phases 1–5 land.  Single review pass across both repos catching anything stale.

| Path | What to check |
|---|---|
| `workbench/workspace/docs/guide.md` | Walks the user through the full workflow.  Update for nested things, examples folder, new commands (status/doctor/dry-run/--env). |
| `ChuMicro-Workspace-Template/README.md` | Quickstart + worked example.  Add examples/ section, nested-things tip, new commands. |
| `ChuMicro-Workspace-Template/AGENTS.md` | Commands table + rules of thumb.  Same updates. |
| `ChuMicro-Workspace-Template/CONTRIBUTING.md` | Verify it still matches the post-Phase-1 layout. |
| `libraries/*/README.md` (12 libraries) | Each one separately — refresh install snippets if Phase 4 changed `pip install` paths. |
| `docs/contributing/*.md` (mono-repo) | Likely has stale references to migrated/deleted scripts. |
| `plans/now.md` + `plans/next-up.md` | Verify after the audit pass. |
| Decision docs `plans/decisions/00**.md` | Decision 0029 (project workspace) and Decision 0038 (workspace template) may need addenda for nested layouts + envs. |

Output: a single audit-results commit per repo with every doc edit.  No new content — only freshening / fact-checking / cross-link repair.

Estimated scope: ~10–20 file edits.  Half a session.

### Phase 7 (parallel track) — Richer REPL

[`plans/workstreams/repl-playground.md`](repl-playground.md) Phase 1a/b/c.  Independent of Phases 1–6; can run in parallel.

* **1a** — line mode + persistent per-device history (~250 LOC)
* **1b** — `:edit` / `:save` / `:load` / `:snippets` (~150 LOC)
* **1c** — tab completion via on-device `dir()` query (~200 LOC)

Detail already drafted in the linked workstream doc.  Not blocked by anything; not blocking anything.

## Out of scope / deferred (after user triage 2026-04-27)

These were on the original Plan C list; user explicitly deferred them.  Captured here so they don't get lost.

| Item | Reason |
|---|---|
| `python run.py deploy --watch` (file-watcher auto-deploy) | "Save for a rainy day" — nice-to-have inner-loop polish, not user-pain-blocking. |
| `python run.py edit <thing>` (open `app.py` + `config.toml` together in `$EDITOR`) | IDE users open the whole workspace already; vim users navigate themselves.  Not enough value-add over `cd things/foo && vim app.py config.toml` for non-IDE users. |
| Multi-device deploys, IF the design sketch isn't simple | Conditional on Phase 2f's first-step assessment.  If reshaping the deploy pipeline is required, defer. |
| Persistent log capture (`python run.py logs <device>`) | **Open design question.**  User flagged this might be a REPL concern rather than a workspace concern.  My take: the *capture* mechanism uses `chumicro_repl.tail()`, but persistent state across sessions is workspace territory (lives in `~/.chumicro/<workspace>/logs/`).  Recommend revisit as part of a later REPL-or-workspace-feature design pass — not in this workstream. |

The following stay in `plans/next-up.md` queue (out of scope for this workstream, will be picked up after it closes):

* Rebrand ChuMicro → ChipPy
* OTA (`plans/workstreams/ota.md`, unscoped)
* Multi-thing-staging cleanup (waits for "build a real second simple thing" trigger; partly subsumed by Phase 1 dropping `switch`)
* `pytest_device` `_test_creds` deploy bridge
* `generate_config_files.py` calling `chumicro_workspace` directly
* Per-runtime adapter helper extraction
* Expand device test matrix beyond ESP32-S2
* Performance benchmarking infrastructure

## Sequencing recommendation

```
Phase 1 (nested things + examples + drop switch)    ← user's directive; biggest win

Phase 2 (ergonomics quick wins) ──┐
Phase 3 (per-env deploys)        ─┼─→ Phase 6 (doc audit)
Phase 4 (scaffolder)             ─┤
Phase 5 (yml knobs)              ─┘

Phase 7 (REPL) — runs in parallel with everything; standalone track
```

Phases 2–5 can land in any order between Phase 1 and Phase 6.  Phase 6 must come last because it's the cleanup pass.  Phase 3 (per-env) is bumped up in priority because the user flagged "implement before it gets hard."

## Acceptance for the workstream as a whole

A user clones [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) and:

1. Runs `python run.py setup` then `python run.py status` to confirm everything's wired.
2. Browses `examples/` to see real worked projects (single-thing + multi-thing).
3. Runs `python run.py new garage/door_open` and gets a nested thing scaffolded.
4. Runs `python run.py deploy garage/door_open --dry-run` to preview what lands.
5. Runs `python run.py deploy garage/door_open --env staging` to deploy with env overrides.
6. Hits `python run.py doctor` when something goes wrong; gets a precise hint.
7. When their app code throws, gets a contextual recovery hint instead of a raw traceback.
8. Reads any of the cross-referenced docs and finds them current.

Plus an advanced user can develop their own chumicro-style libraries with `python run.py new --library mylib` (Phase 4).

## Notes for the executor

* **No backward compatibility.**  Nothing has been published.  Change `THING_NAME` format, CLI flag shapes, file layouts, and remove commands (e.g. `switch`) freely if it makes the design cleaner.  Do NOT add migration logic.
* **Two-repo flow.**  Phases 1, 2, 3, 4, 5 each touch the chumicro mono-repo.  Phases 1 + 6 also touch the template repo (local clone at `/Users/chuxor/circuitpython/ChuMicro-Workspace-Template`).
* **Task-checkpoint per slice.**  Every slice ends with a green preflight + commit + push.  Don't batch slices.
* **Tests come along.**  Every new module gets a test file.  Coverage gate stays at 94 % for changed packages.
* **Templates live in `_payloads/`.**  Canonical scaffolds (thing, library, examples) live under `workbench/workspace/src/chumicro_workspace/_payloads/`.  The template repo's `_templates/` is a *user-owned-config materialisation source* (secrets.yml etc.) — not where scaffolds belong.
