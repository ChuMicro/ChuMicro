# Decision 0093: One transport-factory contract, local copies

Status: `superseded`
Date: `2026-07-03`
Summary: One factory contract for the networking libraries: side-effect-free construction, transports open on first use, lazy adapter import, from_config stays a classmethod; copies stay local.
Related: Decision 0062 (skip-factories deploy mechanism), Decision 0089 (generator surfaces), Decision 0092 (enabled the ntp break)
Superseded by: [Decision 0115](0115-shared-sockets-factories.md)

## Context

The five networking libraries (mqtt, websockets, requests, http_server, ntp) each carry a local
copy of the sockets-factory plumbing.  The 2026-07 audit found the copies had drifted into three
incompatible contracts (M77), and ntp opened its UDP socket eagerly at construction while every
sibling deferred (L52/L53).  The API design pass verdict: define one contract and align each
library in place — copies stay copies, because a shared factory package would add a dependency
edge and another on-flash package to every networking deploy.

## Decision

1. **Construction is side-effect-free.**  Building a client (directly or via `from_config`)
   never opens a socket, resolves DNS, or binds a port.  The transport opens on first use:
   `connect()` (mqtt, websockets), the first request (requests), the first `query()` (ntp), the
   first tick of a started server (http_server).
2. **Factories are injected; adapters import lazily.**  The auto-built factory path imports the
   library's `sockets_factory` module inside `from_config`, guarded by the Decision-0062
   `__chumicro_skip_factories__` escape hatch, and raises a `RuntimeError` naming the explicit
   parameters to pass when the module was excluded from the deploy.
3. **Two factory shapes, by transport role — and only these two.**  Connect-family clients whose
   endpoint varies per call take `(host: str, port: int, use_tls: bool) -> connector` (websockets,
   requests).  Endpoint-baked transports whose address is fixed at configuration time take a
   zero-argument callable returning the transport (mqtt's broker connector, ntp's UDP socket,
   http_server's listener); `from_config` bakes the endpoint into the closure.  Either shape is
   injected through the one kwarg name every library spells identically: `transport_factory=`
   (Decision 0098).
4. **`from_config` stays a classmethod** on the client, reading flat config keys and never
   opening transports (the L52 relocation ask is resolved by this decision going the other way:
   the classmethod is the contract; the factory closure is what defers the cost).

## Consequences

- ntp aligns: `NTPClient(socket=... | transport_factory=...)` (exactly one), the UDP socket
  opens on the first `query()`, and `from_config` defers the auto-built factory into a closure.
  L52 and L53 close.
- The third divergent contract (eager-open) ceases to exist; a new networking library copies
  this contract, not a sibling's incidental shape.
- The copies remain a duplication cost (~65 lines/library, M77) accepted deliberately: deploy
  graphs stay per-library and no shared package rides every flash image.
