# Decision 0098: sockets connect-path collapse + one factory vocabulary

Status: `accepted`
Date: `2026-07-03`
Summary: One connect state machine per runtime behind a single `connector()` entry (12 public callables to 8), and one `transport_factory=` kwarg across the five networked libraries that inject a transport.
Related: 0081 (blocking anti-pattern — edited in place on acceptance), 0093 (factory contract — this completes its vocabulary), 0042 (DI mandate — the patch chain this ends), 0062 (skip-factories — constrains module naming), campaign reports `plans/reviews/2026-07-03-{greenfield-core-redesign,consumer-driven-design-synthesis,consumer-angle-workspace-template}.md`

## Context

sockets maintained two parallel connect paths — the blocking sync-factory family and the
generator connector family — duplicating TLS/deadline/error handling per runtime.  That
divergence class produced the SOCK-2 TLS bake bug and kept the public surface at twelve
callables.  Downstream, the injection kwarg was spelled three ways across the networked
libraries: `connector_factory=` (mqtt, requests, websockets), `socket_factory=` (ntp), and
`listener_factory=` (http_server); the sister repo's flagship additionally carries stale
`socket_factory=` call sites against constructors that no longer accept it.  The DI
measurement says injection itself is near-free; the cost is vocabulary chaos.

## Decision

1. One connect state machine per runtime behind `connector(host, port, *, tls=False,
   context=None, radio=None)` (*radio* is the CP socketpool requirement every entry already
   carries); the blocking sync-factory connect family is deleted (0081's anti-pattern
   becomes unwritable).  The two listening factories merge into `listener(host, port, *,
   tls=False, context=None, backlog=4, radio=None)`.  Public callables go from twelve to
   eight: `connector`, `listener`, `udp_socket`, the four `ssl_context_*` helpers, and
   `set_default_ca_bundle`.
2. One injection kwarg across mqtt, websockets, requests, ntp, http_server:
   **`transport_factory=`** — the word Decision 0093's own title already uses.
   `connector_factory=`, `socket_factory=`, and `listener_factory=` are renamed in the same
   wave, so the sister repo's stale spellings grep as dead code.  sockets itself is the
   producer (its entry is `connector()`, not an injected factory) and wifi injects no
   transport, so neither carries the kwarg.  The `sockets_factory` *module* name survives
   unchanged — Decision 0062's skip-factories matcher keys on it — as does each library's
   local helper (`chumicro_sockets_connector_factory` / `chumicro_sockets_factory` /
   `chumicro_sockets_listener`), which builds connectors and says so.
3. Consumer factory copies shrink (each copy's tcp-vs-tls routing collapses into the single
   entry's `tls=` flag); standalone integrators mirror exactly one function.

Non-runner contexts (one-shot scripts, REPL, host `main` before the runner loop, functional
tests) drive the same connector machine to terminal inline; host-side CPython tooling may
use stdlib `socket` directly.  `workbench/deploy` separately uses the name
`transport_factory` for its serial/USB device transport — an unrelated concept that happens
to share the word.

## Consequences

Every networked library migrated in one wave (0092), gated on the `sweep-devices` bake
matrix including the TLS demo (the path that caught SOCK-2).  0081 §2 and 0093 received
their in-place edits on acceptance.  Template repair (campaign Wave 4) is gated on this
landing.
