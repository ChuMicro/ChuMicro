# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 7 (first end-to-end sensor thing) mostly green: Layer-1 import resolution + Layer-2 fail-fast wifi gates land cleanly on Pi Pico W MP/CP.  Layer-3 broker round-trip blocks on a network-topology issue (device → host LAN IP) that needs physical debugging.
- **Last shipped:** Doc audit — single sweep dropping stale "Slice X" / "Phase 4b/4c" / "future workspace-template" jargon from chumicro-workspace + chumicro-deploy docstrings, CLI help, and one-liner library README claims.  No behavior change.
- **In flight:** —
- **Blocked on:** Phase 7 Layer-3 broker round-trip — deploy succeeds, files reach device (verified via `mpremote fs ls`), but `mosquitto_sub` sees zero messages.  Suspect host LAN-route / firewall.  Needs physical access to dig in.
- **Last touched (this session, post-compact):** `workbench/workspace/src/chumicro_workspace/cli.py` (thing-name validation + Slice/Phase doc cleanup), `workbench/deploy/src/chumicro_deploy/sources.py` (named-from-import submodule resolution), `workbench/workspace/functional_tests/test_sensor_thing_hardware.py` (workaround removed), and a clutch of docstring rewrites in `__init__.py` / `boot_shim.py` / `workspace.py` / `result.py` / `firmware.py` / `recovery.py` / two READMEs.

---

## Workstream summaries (this session)

### Phase 7 — first end-to-end sensor thing

* Layer-1 (`test_sensor_thing_imports_resolve_on_cpython`) and Layer-2 (`test_sensor_thing_reaches_boot_phase_marker_on_{micropython,circuitpython}`) green.
* `chumicro-mqtt` 0.1.2 grew a socket-factory + self-heal hook (`_attempt_self_heal`) so a thing's app can keep the MQTT client across wifi drops without rebuilding the protocol state machine itself.
* Layer-3 (`test_sensor_thing_publishes_to_live_broker`) deploys cleanly — verified the per-runtime adapter files (`chumicro_sockets/_adapters/{cp,mp}.py`, `chumicro_wifi/_adapters/*`, `chumicro_kvstore/_backends/*`) reach the device after adding `extra_modules=_lazy_runtime_adapter_modules()` at the Layer-3 call site.  Broker round-trip itself doesn't yet observe published messages — likely host route/firewall.
* Gap captured in [`plans/workstreams/phase-7-integration.md`](workstreams/phase-7-integration.md): chumicro-deploy's import-graph walker should honor `__chumicro_runtimes__` markers (Decision 0037) and auto-include matching files for the target runtime; that would replace the ad-hoc `extra_modules` workaround.

### Workspace UX — `new` thing-name validation

* `_validate_thing_name` rejects empty / non-identifier / keyword / leading-underscore names with a clear message before any filesystem mutation.  Closes the "I created `things/foo-bar/`, deploys fail with `ImportError`" footgun reported during Phase 7 Layer-3 debugging.

### chumicro-deploy import-graph walker — submodule probing

* `ImportGraphSource._imports_from_file` now also probes `{module}.{alias_name}` for every `from foo.bar import baz`.  Closes the gap where `from chumicro_sockets._adapters import mp` shipped only `_adapters/__init__.py`.  `_lazy_runtime_adapter_modules()` workaround retired from Phase 7 functional tests; `__chumicro_runtimes__`-marker scan idea parked until a library actually does dynamic `importlib` dispatch.

### Doc audit — drop internal phasing jargon

* Single sweep of `Slice X` / `Phase 4b/4c` / `future workspace-template` references that leaked from session notes into public docstrings + CLI help + a couple of READMEs.  Now describes what's actually shipped instead of historical slice numbers.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
