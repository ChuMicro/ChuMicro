# Decision 0081: Library network I/O is non-blocking

Status: `accepted`
Date: `2026-05-23`
Related: Decision 0014 (runner contract), Decision 0031 (chumicro-sockets factories — partially superseded), Decision 0051 (runner-shaped as project policy), Decision 0080 (runner reactor / central wait)

## Context

`chumicro-sockets` today exposes synchronous factories that perform DNS, TCP connect, and the TLS handshake inline before returning a connected socket.  Decision 0031 §2 made this an explicit promise: *"`connect()` happens inside the factory — the returned socket is already connected."*

That promise predates Decision 0080's central-wait carve-out and Decision 0051's runner-shaped rule.  The runner-shaped rule says a leaf service must never block the loop; the only sanctioned blocking point is `Runner.wait`.  But `chumicro_mqtt.MQTTClient.connect()` and `_attempt_self_heal()` both call `socket_factory()` synchronously, which can spend seconds in DNS + TCP + TLS.  Self-heal is the egregious case — it runs inside `handle()`, stalling every other registered service — but `connect()` is symmetrically broken: any caller invoking it from a runner-tick handler stalls the loop the same way.  "Call `connect()` from main before the runner loop starts" is a convention, not a contract.

Bake-validated 2026-05-23 (commit `b7dcad1d`) on Pi Pico W CP custom firmware: the self-heal-after-broker-RST path took ~10 s of full-tick-rate ECONNRESET retries against the wifi radio, fully stalling the runner during the outage.

## Decision

### 1. Library methods that perform network I/O do not block

Generalizing Decision 0051's runner-shaped rule: any library method that performs network I/O — DNS resolution, TCP connect, TLS handshake — yields to the runner between phases.  The convention "callers invoke connect outside the loop" is not a substitute.  The library's contract is "this call returns in bounded time" and bounded means under the runner's tick budget (~5 ms), not "however long the network takes."

### 2. The synchronous factory stays as a carve-out for non-runner contexts

`tcp_client_socket()` and `tls_client_socket()` remain available for one-shot scripts, REPL exploration, tests that want a fully-connected socket immediately, and code that genuinely owns the loop (a `main` that does setup before entering the runner loop).  Library code that's runner-shaped — anything under `libraries/` that registers with a Runner and exposes `check` / `handle` / `io_*` — uses non-blocking forms exclusively.

Same shape Decision 0080 took for blocking poll: the leaf rule bans `poll(timeout > 0)`, the central-wait carve-out allows it in `Runner.wait`.

## Rejected

- **EINPROGRESS-style "partially-connected socket" return.**  Factory returns a raw socket mid-connect, caller polls POLLOUT + checks SO_ERROR.  Offloads the TLS handshake state machine onto every caller; chumicro-mqtt, chumicro-requests, chumicro-websockets, chumicro-http-server would each reimplement it.  A connector object owns the handshake state once.
- **Async / await across runtimes.**  Decision 0080 §Rejected covers this in detail — coroutine-bound I/O reactor is incompatible with the tick-based runner; same reasoning applies to non-blocking connect.
- **Removing self-heal entirely** (the reference impl's pattern of `loop()`-raises-on-dead-connection + caller-handles-reconnect).  Pushing reconnect onto application code violates the runner-shaped model "the library tells the runner what it needs, the runner gives it time slots."  The library owns reconnect; this ADR makes it non-blocking.
- **Per-runtime "fake" non-blocking on CircuitPython** (spawn a thread, do the synchronous connect there).  CP doesn't have threads and the patterns we'd need to fake don't exist on the substrate.  CP's substrate limit is what it is; per-phase blocking on CP is the honest answer.

## Consequences

- **Decision 0031 §2 is edited in place.**  The promise *"`connect()` happens inside the factory — the returned socket is already connected"* now applies only to the synchronous factories; the new non-blocking forms are non-blocking by contract.  §2 names both forms and which is appropriate when.
- **Decision 0051's runner-shaped rule list grows by one bullet.**  In addition to `time.sleep(N > 0.005)` and `select.poll(timeout > 0)`, library methods that perform network I/O don't block — including connect.  The carve-out is the synchronous factories under `chumicro_sockets` for non-runner contexts.
- **Implementation is tracked separately** in [`plans/workstreams/archive/non-blocking-connect-implementation.md`](../workstreams/archive/non-blocking-connect-implementation.md).  The workstream covered the connector contract, per-runtime substrate handling (CPython EINPROGRESS / MP rp2 / CP socketpool's blocking compromise), `MQTTClient`'s state-machine migration, and the `chumicro-requests` / `chumicro-websockets` migrations.  Phases 1.1, 1.2, 1.3, 2, 4, and 5 shipped; Phase 6 (http-server) was deferred.
- **The runner-shaped policy clarification cascades.**  Library audits (`/audit-embedded chumicro_mqtt`, `/audit-library chumicro_sockets`) should flag any other library method that does synchronous network I/O.  Likely candidates: chumicro-ntp's `query`, chumicro-wifi's `connect` (separate ADR scope; not in this one).
