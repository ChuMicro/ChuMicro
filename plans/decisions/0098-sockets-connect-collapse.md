# Decision 0098: sockets connect-path collapse + one factory vocabulary

Status: `proposed`
Date: `2026-07-03`
Summary: One connect state machine per runtime behind a single `connector()` entry (12 public callables to 8), and one `transport_factory=` kwarg across the five networked libraries.
Related: 0081 (blocking anti-pattern — edited in place on acceptance), 0093 (factory contract — this completes its vocabulary), 0042 (DI mandate — the patch chain this ends), campaign reports `plans/reviews/2026-07-03-{greenfield-core-redesign,consumer-driven-design-synthesis,consumer-angle-workspace-template}.md`

## Context

sockets maintains two parallel connect paths — the blocking sync-factory family and the
generator connector family — duplicating TLS/deadline/error handling per runtime.  That
divergence class produced the SOCK-2 TLS bake bug and keeps the public surface at twelve
callables.  Downstream, the five networked libraries spell their injection kwarg three
ways (`connector_factory=`, `sockets_factory=`, and the now-obsolete `socket_factory=`
that the sister repo's flagship still uses against a constructor that no longer has it).
The DI measurement says injection itself is near-free; the cost is vocabulary chaos.

## Decision

1. One connect state machine per runtime behind `connector(host, port, *, tls=False,
   context=None)`; the blocking sync-factory connect family is deleted (0081's
   anti-pattern becomes unwritable).  Public callables go from twelve to eight.
2. One injection kwarg across sockets, wifi, mqtt, websockets, requests, ntp,
   http_server: **`transport_factory=`** — the word Decision 0093's own title already
   uses.  `connector_factory=` and `sockets_factory=` are renamed in the same wave;
   `socket_factory=` stays dead, so the sister repo's stale code greps as dead code.
3. Consumer factory copies shrink from ~200 to ~70 lines; standalone integrators mirror
   exactly one function.

## Consequences

Every networked library migrates in one wave (0092), gated on the `sweep-devices` bake
matrix including the TLS demo (the path that caught SOCK-2).  The stripped sockets
module drops ~9 KB.  0081 and 0093 receive their in-place edits on acceptance.  Template
repair (campaign Wave 4) is gated on this landing.
