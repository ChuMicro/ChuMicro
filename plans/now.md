# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Shipped the config-shape-beginner-ergonomics workstream end-to-end.  Three files (workspace.yml machinery / secrets.toml device-bound / project_config.toml per-project), flat-key `RuntimeConfig` wrapper on the device, `WifiConfig.from_config(config)` replaces `from_dict`, `[tool.chumicro.config] required_keys = [...]` manifest format, `chumicro-workspace config-validate` CLI, additive setup re-apply preserves comments via tomlkit + ruamel round-trip.  ADRs 0036 + 0057 refreshed in place.  Hardware-validated on all four boards (Pi Pico W CP/MP + Lolin S2 CP/MP) — wifi acceptance 12/12 + MQTT round-trip 4/4.  VERSIONs: chumicro-config 0.2.0, chumicro-wifi 0.1.0, chumicro-workspace 0.12.0.
- **Last shipped:** `Add config-validate CLI + additive setup re-apply; refresh ADRs 0036 / 0057` (commit `7d36f27`); template-repo `Migrate to flat-key runtime config + secrets.toml + project_config.toml` (commit `72c6ffb`).
- **In flight:** idle.  Pickup candidates in `next-up.md` `## Next` — the on-device-config-dogfooding workstream remains ready (still needs the pytest-device plugin hook for late-binding broker / echo / WS-server values; the seven mono-repo conftests already use the flat-key shape this workstream landed).  Side-task chip open: declare `[tool.chumicro.config]` manifests in the six networking libraries that don't have one yet (Q11 follow-up).
- **Blocked on:** —.
- **Last touched:** `plans/workstreams/archive/config-shape-beginner-ergonomics.md`, `plans/decisions/0036-chumicro-config-library.md`, `plans/decisions/0057-two-file-config.md`, `plans/next-up.md`, mono-repo + template repo per the commit list above.

---

## What a fresh session should read first

1. This file (`plans/now.md`).
2. `git --no-pager log --oneline -20` — what just shipped, in order.
3. `plans/next-up.md` — queue (`## Now`) + recent done log.
4. `plans/decisions/` — only when proposing structural changes.

## Pick-up candidates (sorted by readiness)

| Candidate | Where | Notes |
|---|---|---|
| Declare `[tool.chumicro.config]` manifests in the six networking libraries that lack one (mqtt, requests, http_server, sockets, websockets, ntp) | `plans/workstreams/archive/config-shape-beginner-ergonomics.md` Q11 follow-up | Mechanical — copy the wifi pyproject pattern; each library declares the flat keys its `from_config` reads.  Unblocks `chumicro-workspace config-validate` to actually catch missing config across the whole stack instead of only wifi. |
| On-device config dogfooding (was Phase 4.5b) | `plans/workstreams/on-device-config-dogfooding.md` | Plan validated + edited; ready to pick up cold.  Step 1 = plugin hook design + wifi as first consumer + 4-board hardware validation; Steps 2-4 mechanical.  (Note: the seven mono-repo conftests already use the flat-key shape — the remaining work is the late-binding broker / echo / WS-server plugin hook in chumicro-pytest-device.) |
| Anything in `## Next` of `next-up.md` | `plans/next-up.md` | OTA workstream (`plans/workstreams/ota.md`), digital I/O library, performance benchmarking infrastructure, etc.  All are unscoped or trigger-gated. |

## Hard rules to remember (non-negotiables)

- **`AGENTS.md` non-negotiables apply.**  Read it on session start.
- **No backward compatibility burden.**  Nothing's published to PyPI yet — change formats, flags, layouts freely.  Do not add migration logic.
- **Task-checkpoint per slice.**  Every coherent unit ends with green preflight (`python scripts/run.py preflight --coverage-threshold 94`) + commit + push.
- **`git commit -F .scratch/commit-msg.txt`** — write the message to a file via Write tool, then `git commit -F`.  No `-m`, no heredocs in the terminal.  No `Co-Authored-By: Claude` trailer.
- **Two-repo flow.**  The mono-repo is at `/Users/chuxor/circuitpython/chumicro`; the workspace template repo is at `/Users/chuxor/circuitpython/ChuMicro-Workspace-Template`.  Several workstreams touch both.
- **Branching policy.**  Repo is private — commit directly to `main`; no PRs.
- **All four boards plugged in.**  `devices.yml` registers Lolin S2 (CP+MP) and Pi Pico W (CP+MP).  Hardware-functional tests are runnable via `python scripts/run.py test-workbench-functional` / `test-libraries-functional`.

## How this file works

- One screen, never more.
- Overwritten, not appended.  Older snapshots are recoverable from `git log plans/now.md`.
- Updated in step 4 of `task-checkpoint`.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue.
