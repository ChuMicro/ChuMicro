# Decision 0118: from_config forwards unknown keywords to the constructor

Status: `accepted`
Date: `2026-08-09`
Summary: Every service `from_config` forwards extra keyword arguments to the constructor verbatim; an explicit keyword beats its config-derived value. Manifest keys stay the curated deployment-varying set.
Related: Decision [0115](0115-shared-sockets-factories.md) (the factory seams `from_config` builds on), the seam-coherence workstream (`plans/workstreams/seam-coherence.md`)

## Context

`MQTTClient.from_config` forwarded six of roughly twenty constructor knobs.  Anything else, the buffer tunables above all, forced the caller back to a hand-built client: `examples/bench.py` reconstructed the whole transport factory just to pass `rx_buffer_size`.  The pressure was visible elsewhere too.  `WebSocketServer.from_config` had grown ad-hoc named forwarding for `accept_path` and `max_connections`, `HttpClient.from_config` never forwarded `ticks` at all, and each library drew its own line on which knobs deserve a seat.

Three shapes were considered:

1. **A manifest key per knob.**  Twenty keys per library, five libraries.  Most of those knobs (queue caps, per-tick budgets, buffer sizes) are architecture decisions the code makes once per project, not values a fleet operator varies per site, so promoting them to config keys misstates who owns them.  It also cannot cover the callable seams (`transport_factory`, `handler`, `on_connection`).
2. **Keep the curated sets and accept hand-building.**  The status quo: honest but leaky, as the bench and the websockets drift showed.
3. **A generic keyword passthrough.**  Config keys keep carrying the deployment-varying values; everything else rides as a keyword.

## Decision

Every service `from_config` (mqtt, ntp, requests, http_server, websockets server and client) takes `**constructor_kwargs` and forwards them to the constructor verbatim.  Collision policy: the explicit keyword wins over the config-derived value, because the caller writing code is more specific than the manifest.  Implementation is uniform: build the config-derived kwargs dict, `update()` it with the passthrough, call the constructor once.

The curated manifest-key sets stay as they are.  The line they draw is ownership: a config key is a value a deployment varies without touching code (addresses, credentials, client identity, keepalive, offline policy); a constructor knob is a value the application owns (buffers, budgets, queue caps, callbacks, injected substrates).  The named injection-seam parameters (`radio`, `ssl_context`, `socket`/`listener`, `transport_factory`, `ticks`) also stay named: they are documented seams, and several gate lazy imports.

Out of scope: `WifiConfig.from_config` is a config-section loader, not a service constructor, and wifi's missing service-level `from_config` remains a seam-coherence workstream item.

## Consequences

- A tuned client is one call: `MQTTClient.from_config(config, radio=radio, rx_buffer_size=1024)`.  `examples/bench.py` dropped its hand-built factory.
- `ticks` now reaches every constructor through `from_config`, closing that half of the seam-coherence drift.
- A typo in a passthrough keyword surfaces as the constructor's own `TypeError`, naming the bad keyword at the call site.
- `WebSocketServer.from_config`'s named `accept_path` and `max_connections` parameters stay for compatibility; they are now just early-bound instances of the general pattern.
