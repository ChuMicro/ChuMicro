# Now

> **Agent-managed file.**  Refreshed every `task-checkpoint`.  Cross-maintain with [`next-up.md`](next-up.md): when a workstream lands, update the snapshot here AND move the matching `## Now` entry into `## Done` over there in the same commit.  ≤25 lines total — overflow into `next-up.md` or a workstream file, not here.

- **Phase:** Shipped the config-shape-beginner-ergonomics workstream end-to-end.  Three files (workspace.yml machinery / secrets.toml device-bound / project_config.toml per-project), flat-key `RuntimeConfig` wrapper on the device, `WifiConfig.from_config(config)` replaces `from_dict`, `[tool.chumicro.config] required_keys = [...]` manifest format, `chumicro-workspace config-validate` CLI, additive setup re-apply preserves comments via tomlkit + ruamel round-trip.  ADRs 0036 + 0057 refreshed in place.  Hardware-validated on all four boards (Pi Pico W CP/MP + Lolin S2 CP/MP) — wifi acceptance 12/12 + MQTT round-trip 4/4.  VERSIONs: chumicro-config 0.2.0, chumicro-wifi 0.1.0, chumicro-workspace 0.12.0.
- **Last shipped:** `chumicro-deploy: simplify implementation-version probe to a [:3] slice` (commit `09fc619`) — replaced the defensive walk-while-int loop with a 3-slot slice after live-probing all four boards + reading upstream `py/modsys.c` confirmed both CP and MP always emit a 4-tuple `(int, int, int, str)`.
- **In flight:** idle.  Pickup candidates live in [`next-up.md`](next-up.md) `## Next`.
- **Blocked on:** —.
- **Last touched:** `workbench/deploy/src/chumicro_deploy/protocol.py`, `workbench/deploy/tests/test_protocol.py` for the probe-slice cleanup.
