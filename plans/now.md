# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** workspace-bootstrap pivot (Decision 0038) landing.  `chumicro-workspace-runtime` renamed to `chumicro-workspace`; `chumicro-workspace-template` package deleted; `init` / `update` folded into the renamed package; canonical workspace template moved to a separate private repo at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template); `setup` now materializes `_templates/secrets.yml` → `secrets.yml` so users never `cp` an `.example` file.  `check-version` waives the bump gate while VERSION reads `0.0.0`.
- **Last shipped:** Pi Pico W flash-footprint workstream (Decision 0037 + macOS-FAT hygiene; ~80 KB recovered, all 9 libs fit on Pi Pico W CP).
- **In flight:** Decision 0038 pivot — staged template content lives in `.scratch/template-repo/` ready to push to the new private repo once the in-mono-repo commit lands.
- **Blocked on:** —
- **Last touched:** `plans/decisions/0038-workspace-bootstrap-via-clone.md`, `workbench/workspace/` (renamed from `workspace-runtime/`), new `chumicro_workspace.template_zones` + `chumicro_workspace.template_apply` modules with `init`/`update`/`materialize_templates`, deleted `workbench/workspace-template/`, `scripts/check_version.py` (0.0.0 floor), `.scratch/template-repo/` (12 files staged for the new repo), root README.md / AGENTS.md / docs/contributing/workbench.md package roster.

---

## Workstream summary (workspace bootstrap pivot, this session)

* **Decision 0038** documents the shift: the workspace template is a Git repo users clone, not a `_payloads/` blob shipped inside a workbench package.  Restores Decision 0029 §1's "the workspace is a git repo" promise.
* **Package consolidation:** `chumicro-workspace-template` deleted; its `init` / `update` / three-zone manifest folded into `chumicro-workspace` (renamed from `chumicro-workspace-runtime`).  One CLI, one folder, one VERSION.
* **Self-bootstrapping `run.py`:** the new template repo's `run.py` creates `.venv` + installs `chumicro-workspace` on first `python3 run.py setup` and re-execs into the venv for every subsequent command.  No prerequisite pip install of any ChuMicro package needed.
* **Templated config files (Decision 0038 §5):** `secrets.yml.example` retired.  Template sources live under `_templates/` and `setup` materializes them into the workspace root (idempotent, never overwrites user edits).
* **`check-version` 0.0.0 carve-out (Decision 0038 §6):** packages at the pre-release floor are exempt from the bump gate; gate kicks in once VERSION crosses to non-zero.

Side cleanup: stale `topic_ai/great-bell-304fe5` branch deleted from origin; PR #1 (stale 0.1.12 bump) flagged for manual close from the GitHub UI; `.idea/chumicro.iml` PyCharm drift reverted via `sync-ide`.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
