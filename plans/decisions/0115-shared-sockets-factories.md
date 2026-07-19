# Decision 0115: Shared sockets factories

Status: `accepted`
Date: `2026-07-18`
Summary: Five per-library transport-factory copies collapse into one generic module, chumicro_sockets.sockets_factory, taking host/port/TLS only; each from_config keeps its own config-key extraction.
Related: Decision 0062 (skip-factories deploy mechanism), Decision 0092 (no backwards-compat before publication), Decision 0093 (superseded predecessor: local copies), Decision 0098 (transport_factory kwarg)

## Context

The five networking libraries (mqtt, requests, websockets, http_server, ntp) each carried a local copy of the transport-factory wiring. Decision 0093 kept the copies local to avoid a shared package riding every networking deploy. The 2026-07 audit found the copies had drifted into three incompatible contracts (finding M77) before a hand-realignment pulled them back together; nothing but review discipline held five copies to one contract. Decision 0092 removed the backwards-compat constraint that would have made a relocation a multi-step migration, so the copies can now move in one break-plus-migrate pass.

## Decision

One module, `chumicro_sockets.sockets_factory`, holds the four generic builders: `connector_factory`, `fixed_connector_factory`, `listener_factory`, and `udp_socket_factory`. They take hosts, ports, and TLS material as parameters and nothing else.

- **The shared home is chumicro_sockets.** Every importer of the glue is a sockets user by definition: the builders call `chumicro_sockets.connector` / `listener` / `udp_socket`, so the dependency edge the copies were meant to avoid already exists wherever a factory runs.
- **Generic parameters only; no protocol config namespaces.** The builders never read `mqtt.broker.host` or any protocol key. Each library's `from_config` keeps its own config-key extraction and passes the plain host, port, and TLS values in. Sockets learns no protocol vocabulary, so the dependency direction stays clean.
- **The filename ends in `_factory`.** The deploy walker's `__chumicro_skip_factories__` family matching (Decision 0062, `_FACTORY_STEM`) drops the one shared module from bring-your-own-transport deploys with zero walker changes, exactly as it dropped the five copies.
- The transport-factory contract itself carries over from the superseded Decision 0093: side-effect-free construction, lazy import guarded by the skip-factories hatch, the two factory shapes by transport role, and `from_config` as a classmethod. Only the home of the shared builders moved.

## Consequences

- One contract lives in one file. The M77 drift class cannot recur, because there is no second copy to drift from.
- Measured cost: the sockets mpy artifact grew 159 bytes (15672 to 15831); its stripped size is unchanged. All five migrated libraries shrank, with headroom on both size dimensions. check-size stays green and no other budget moved; only the `[sockets]` mpy ceiling rose, by the measured 159 bytes.
- A new networking library imports the shared builders instead of copying a sibling's file.
- Decision 0093 is superseded: its "local copies" premise no longer describes repo state.
