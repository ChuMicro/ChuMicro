# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 4a Slice 0 shipped — `chumicro-workspace-runtime` skeleton + deploy-time config-merge core (workspace defaults + per-thing config + secrets → `/runtime_config.msgpack` per ADR 0035). Subsequent slices add command dispatch, three-zone YAML writer, onboarding flows, firmware URL derivation, import-graph resolver.
- **Last shipped:** Phase 4a Slice 0 — `workbench/workspace-runtime/` package with `merge_configs` (deep per-key merge), `resolve_secrets` (`!secret <name>` reference resolution), file loaders for `workspace.yml` + `things/<name>/config.{toml,yml,yaml}` + `secrets.yml`, msgpack writer, and the `build_runtime_config` end-to-end pipeline. 46 host tests at 100 % coverage.
- **In flight:** Phase 4a Slice 1 — wire `chumicro-deploy`'s deploy flow to call `build_runtime_config` so deploys auto-generate the runtime-config msgpack from each thing's source files.
- **Blocked on:** —
- **Last touched:** `workbench/workspace-runtime/**`, IDE config sync. Phase 3a + 3b both feature-complete; Phase 4a is the integration phase wiring the deploy + on-device sides together.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
