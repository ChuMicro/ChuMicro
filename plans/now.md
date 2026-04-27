# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** **Workspace-template testing-infrastructure audit** (just promoted from `## Next` 2026-04-27).  Just-completed two-phase scripts→workbench migration sets up the natural follow-on: the user-facing `ChuMicro-Workspace-Template` starter repo can now adopt `chumicro-pytest-device` 0.1.0 as a real dep instead of copying the plugin.  Goal of the audit: figure out what test/lint/coverage scaffolding the template ships today and what's missing vs the mono-repo's `preflight` surface.  Then ship whatever's missing — preferred location is in the template itself; fallback is having `chumicro-workspace setup` materialise it.
- **Last shipped:**
  * `e76b9f9` — Phase 1: device-registry schema (DeviceEntry / DeviceDefaults / validators / loaders / filters / `resolve_ide_devices`) migrates from `scripts/device_config.py` to `chumicro_deploy.config.default`.  17 consumers updated, dead `device-config.yml` flow dropped.  `chumicro-deploy` 0.0.1 → 0.1.0.
  * `3e01cbf` — Phase 2: extract `chumicro-pytest-device` 0.1.0 workbench package.  Plugin (1242 lines) + 3 helpers (~775 lines) move out of `scripts/`.  Auto-registers via `pytest11` entry point — drops the explicit `pytest_plugins = ["pytest_device"]` from root conftest.  ROOT constant lifted via `pytest.Config.rootpath` so the plugin works inside any workspace, not just chumicro mono-repo.  Bonus: fixes a subtle pytest-cov instrumentation gap caused by entry-point auto-load running before pytest-cov starts.
- **In flight:** Promote the audit to `## Now` (done in this same session).  Refresh `plans/next-up.md` (done).  Start the audit itself — investigate the `ChuMicro-Workspace-Template` repo and identify gaps.
- **Blocked on:** —
- **Last touched:** `workbench/deploy/src/chumicro_deploy/{__init__.py,config/default.py}` (Phase 1 schema migration), `workbench/pytest-device/{VERSION,pyproject.toml,README.md,src/chumicro_pytest_device/{plugin,_test_runner,pr_summary,result_parser}.py,tests/}` (Phase 2 new package), `scripts/run.py` (`-p no:chumicro_pytest_device` injection for unit-test runs), `scripts/{pytest_device,pr_summary,result_parser,device_testing,device_config}.py` deleted, `conftest.py` (drop `pytest_plugins` line).

---

## Architectural state after Phase 1+2

* `chumicro-deploy` 0.1.0 — owns `Device`, `Deployer`, `InteractiveDeployer`, `DeviceEntry` registry schema, transport protocol.  Public deploy primitives + the YAML schema everything reads.
* `chumicro-pytest-device` 0.1.0 — owns the pytest plugin that runs library functional tests on connected boards.  `pip install` registers it via `pytest11` entry point.
* `chumicro-workspace`, `chumicro-repl` — unchanged.
* `chumicro-workspace-template` workbench package — minimal payload (just `devices.yml`); the canonical starter content lives at the [external `ChuMicro-Workspace-Template` Git repo](https://github.com/ChuMicro/ChuMicro-Workspace-Template) per Decision 0038.
* `scripts/` — shrunk from ~9.9K lines to ~7.6K.  What remains is genuine mono-repo CI plumbing (release pipeline, bundle staging, runtime preparation, IDE config, gates).  Backlog reviewed 2026-04-27 and confirmed: nothing else has a clear workbench-package home without a real consumer driver.

## Workspace-template audit — what to look for

The template ships a `run.py` shim (per Decision 0038's clone-the-repo bootstrap).  Open questions for the audit:

1. **Unit tests:** does the template have a `tests/` dir + `run.py test` command for the user's own test code?  If not, what's the minimum-viable starter?
2. **Functional tests:** does the template support `things/<name>/functional_tests/`?  Does it adopt `chumicro-pytest-device` as a dep, or copy/reimplement the plugin?
3. **Lint:** does the template ship a `ruff` config that matches the mono-repo's tone?
4. **Coverage gate:** does the template enforce a coverage threshold on user code?  85 % default (matching the mono-repo's human floor) or none?
5. **CI:** does the template ship a GitHub Actions workflow (or analogue) so the user's `things/` get tested on every push without manual `run.py` invocation?
6. **`chumicro-pytest-device` adoption:** brand-new dep candidate.  When the template adopts it, the auto-register entry point Just Works — no extra wiring in the template's `conftest.py`.

Action ordering: read the template repo (WebFetch), survey what's there, propose concrete additions, ship them either inside the template or via `chumicro-workspace setup` materialisation.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
