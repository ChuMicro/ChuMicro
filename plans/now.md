# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** idle — Decision 0038 workspace-bootstrap pivot landed (2026-04-26); chumicro-dev mode wired into the template repo; `scripts/device_config.py` migrated to consume `chumicro_deploy.config.default.load_raw_entries`.  Pick the next item from `plans/next-up.md` (Phase 7 sensor thing template, scripts→workbench backlog, multi-thing flash re-eval, or rebrand-to-ChipPy are top of the queue).
- **Last shipped:** `scripts/device_config.py` consumes `chumicro_deploy.config.default.load_raw_entries` (Decision 0032 rule 8 cleanup; one place defines the devices.yml schema, mono-repo + chumicro-deploy tests stay in sync).
- **In flight:** —
- **Blocked on:** —
- **Last touched:** `workbench/deploy/src/chumicro_deploy/config/default.py` (new `load_raw_entries` primitive + `load_devices_yml` rewired through it), `workbench/deploy/tests/test_config_default.py` (9 new `TestLoadRawEntries` cases), `scripts/device_config.py` (`load_device_registry` now wraps `load_raw_entries`).

---

## Workstream summaries (this session)

### Decision 0038 pivot

* Renamed `chumicro-workspace-runtime` → `chumicro-workspace`; folded `init` / `update` / three-zone manifest in.
* Created [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template) as the canonical Git template repo (private, GitHub template-flagged).
* Self-bootstrapping `run.py` + `_templates/` materialization (Decision 0038 §5).
* `check-version` waives the bump gate at 0.0.0 (Decision 0038 §6).
* chumicro-dev mode: `chumicro-dev.toml` points at a local chumicro mono-repo path; `run.py setup` walks `libraries/` + `workbench/` and pip-installs each as editable.  Smoke-tested end-to-end.
* Side cleanup: gitconfig includeIf at `~/circuitpython/.gitconfig` so any repo under `~/circuitpython/` auto-uses `ChuxMaker / chuxmaker@users.noreply.github.com` (was committing under the wrong identity twice before this got wired up).

### `scripts/device_config.py` migration

* New `load_raw_entries(path) -> (entries, defaults)` primitive in `chumicro_deploy.config.default` — pure YAML parse, no Device construction.
* `load_devices_yml` rewired through the primitive.
* `scripts/device_config.py` `load_device_registry` wraps it; script-only surface (DeviceEntry / DeviceDefaults / `_validate_device` / `filter_devices` / `resolve_ide_devices`) preserved verbatim so `device_testing`, `pytest_device`, `pr_summary`, and `workbench/deploy/functional_tests/conftest.py` don't change.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
