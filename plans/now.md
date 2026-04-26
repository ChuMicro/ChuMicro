# Now

**30-second brain snapshot.** Refreshed every `task-checkpoint`. If this file is stale, that means the last session ended without checkpointing — fall back to `git log -10` and `plans/next-up.md`.

This is the front door. Everything else is deeper read.

---

- **Phase:** Phase 7 (first end-to-end sensor thing) mostly green: Layer-1 import resolution + Layer-2 fail-fast wifi gates land cleanly on Pi Pico W MP/CP.  Layer-3 broker round-trip blocks on a network-topology issue (device → host LAN IP) that needs physical debugging.
- **Last shipped:** `ImportGraphSource` now resolves named-from-import submodules (`from chumicro_sockets._adapters import mp` ships `mp.py`); the `_lazy_runtime_adapter_modules()` workaround retired from the Phase 7 functional tests.
- **In flight:** —
- **Blocked on:** Phase 7 Layer-3 broker round-trip — deploy succeeds, files reach device (verified via `mpremote fs ls`), but `mosquitto_sub` sees zero messages.  Suspect host LAN-route / firewall.  Needs physical access to dig in.
- **Last touched:** `workbench/deploy/src/chumicro_deploy/sources.py` (`_imports_from_file` probes `{module}.{alias_name}` candidates from `ImportFrom` nodes), `workbench/deploy/tests/test_sources.py` (3 new submodule-probing cases), `workbench/workspace/functional_tests/test_sensor_thing_hardware.py` (drop the workaround), `plans/workstreams/phase-7-integration.md` (mark gap resolved).

---

## Workstream summaries (this session)

### Phase 7 — first end-to-end sensor thing

* Layer-1 (`test_sensor_thing_imports_resolve_on_cpython`) and Layer-2 (`test_sensor_thing_reaches_boot_phase_marker_on_{micropython,circuitpython}`) green.
* `chumicro-mqtt` 0.1.2 grew a socket-factory + self-heal hook (`_attempt_self_heal`) so a thing's app can keep the MQTT client across wifi drops without rebuilding the protocol state machine itself.
* Layer-3 (`test_sensor_thing_publishes_to_live_broker`) deploys cleanly — verified the per-runtime adapter files (`chumicro_sockets/_adapters/{cp,mp}.py`, `chumicro_wifi/_adapters/*`, `chumicro_kvstore/_backends/*`) reach the device after adding `extra_modules=_lazy_runtime_adapter_modules()` at the Layer-3 call site.  Broker round-trip itself doesn't yet observe published messages — likely host route/firewall.
* Gap captured in [`plans/workstreams/phase-7-integration.md`](workstreams/phase-7-integration.md): chumicro-deploy's import-graph walker should honor `__chumicro_runtimes__` markers (Decision 0037) and auto-include matching files for the target runtime; that would replace the ad-hoc `extra_modules` workaround.

### Workspace UX — `new` thing-name validation

* `_validate_thing_name` rejects empty / non-identifier / keyword / leading-underscore names with a clear message before any filesystem mutation.  Closes the "I created `things/foo-bar/`, deploys fail with `ImportError`" footgun reported during Phase 7 Layer-3 debugging.

---

## How this file works

- One screen, never more. If a section grows past two lines, it belongs somewhere else.
- Overwritten, not appended. Older snapshots are recoverable from `git log plans/now.md`.
- The agent updates this in step 4 of `task-checkpoint`. Humans can update it manually too.
- "Phase" / "In flight" / "Blocked on" are the load-bearing fields. The others are convenience.

If you're an agent picking up cold: read this, then `git --no-pager log --oneline -20`, then `plans/next-up.md` if you need the queue. That's the warm-up. Everything else (`history.md`, `decisions/`, `patterns.md`, `learnings.md`, workstreams) is deep-dive on demand.
