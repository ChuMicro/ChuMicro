# Decision 0081: Library network I/O is non-blocking

Status: `accepted`
Date: `2026-05-23`
Summary: Library network I/O never blocks; the tick-driven connector (DNS → TCP → TLS, one phase per tick) is the only connect implementation; non-runner contexts drive it to terminal inline.
Related: Decision 0014 (runner contract), Decision 0031 (chumicro-sockets factories — partially superseded), Decision 0051 (runner-shaped as project policy), Decision 0080 (runner reactor / central wait), Decision 0098 (connect-path collapse — retired the synchronous carve-out)

## Context

`chumicro-sockets` today exposes synchronous factories that perform DNS, TCP connect, and the TLS handshake inline before returning a connected socket.  Decision 0031 §2 made this an explicit promise: *"`connect()` happens inside the factory — the returned socket is already connected."*

That promise predates Decision 0080's central-wait carve-out and Decision 0051's runner-shaped rule.  The runner-shaped rule says a leaf service must never block the loop; the only sanctioned blocking point is `Runner.wait`.  But `chumicro_mqtt.MQTTClient.connect()` and `_attempt_self_heal()` both call `socket_factory()` synchronously, which can spend seconds in DNS + TCP + TLS.  Self-heal is the egregious case — it runs inside `handle()`, stalling every other registered service — but `connect()` is symmetrically broken: any caller invoking it from a runner-tick handler stalls the loop the same way.  "Call `connect()` from main before the runner loop starts" is a convention, not a contract.

Bake-validated 2026-05-23 (commit `b7dcad1d`) on Pi Pico W CP custom firmware: the self-heal-after-broker-RST path took ~10 s of full-tick-rate ECONNRESET retries against the wifi radio, fully stalling the runner during the outage.

## Decision

### 1. Library methods that perform network I/O do not block

Generalizing Decision 0051's runner-shaped rule: any library method that performs network I/O — DNS resolution, TCP connect, TLS handshake — yields to the runner between phases.  The convention "callers invoke connect outside the loop" is not a substitute.  The library's contract is "this call returns in bounded time" and bounded means under the runner's tick budget (~5 ms), not "however long the network takes."

### 2. One implementation — the connector is also the one-shot form

There is no synchronous factory (Decision 0098 deleted `tcp_client_socket()` /
`tls_client_socket()`; a second connect implementation per runtime was the divergence
class that produced the SOCK-2 TLS bake bug).  The sanctioned one-shot forms are:

- **On-device / cross-runtime** — drive the same `connector()` machine to terminal inline
  (a small `tick()`-until-`ready`/`failed` loop, or `runner.run_until` when a runner is
  already in hand; `run_until` made the loop ergonomic).  One-shot scripts, REPL
  exploration, and `main`-before-the-loop pay a trivial while-loop instead of carrying a
  parallel blocking implementation.
- **Host-side CPython tooling** (test fixtures, demo drivers) — stdlib `socket` directly;
  host tooling is not device code and never was the anti-pattern this decision targets.

Library code that's runner-shaped — anything under `libraries/` that registers with a
Runner and exposes `check` / `handle` / `io_*` — registers the connector or drives it from
its own state machine, never blocking a tick beyond the documented per-runtime substrate
compromises.

## Rejected

- **EINPROGRESS-style "partially-connected socket" return.**  Factory returns a raw socket mid-connect, caller polls POLLOUT + checks SO_ERROR.  Offloads the TLS handshake state machine onto every caller; chumicro-mqtt, chumicro-requests, chumicro-websockets, chumicro-http-server would each reimplement it.  A connector object owns the handshake state once.
- **Async / await across runtimes.**  Decision 0080 §Rejected covers this in detail — coroutine-bound I/O reactor is incompatible with the tick-based runner; same reasoning applies to non-blocking connect.
- **Removing self-heal entirely** (the reference impl's pattern of `loop()`-raises-on-dead-connection + caller-handles-reconnect).  Pushing reconnect onto application code violates the runner-shaped model "the library tells the runner what it needs, the runner gives it time slots."  The library owns reconnect; this ADR makes it non-blocking.
- **Per-runtime "fake" non-blocking on CircuitPython** (spawn a thread, do the synchronous connect there).  CP doesn't have threads and the patterns we'd need to fake don't exist on the substrate.  CP's substrate limit is what it is; per-phase blocking on CP is the honest answer.
- **Deferred TLS handshake stepped from the tick loop on MicroPython** (`wrap_socket(do_handshake_on_connect=False)`, then advance per tick).  Attempted twice and unshippable on MicroPython 1.27: a one-byte `readinto` does step the handshake and does surface certificate-verify failures, but the runtime exposes no safe signal that the handshake has completed — `getpeercert` is absent (MicroPython's standalone mbedTLS config never enables peer-certificate retention), `SSLSocket.cipher()` crashes when called before the session exists, and a zero-length write returns from the stream layer without reaching mbedTLS at all.  A bring-up that cannot observe completion cannot promote provably, so MicroPython's TLS handshake blocks inside `wrap_socket`, the same substrate-compromise class as CircuitPython's per-phase blocking above.  Upstream engagement is not on the table for this project, so the compromise stands as long as the pinned MicroPython holds these surfaces.

## Consequences

- **Decision 0031 §2 is edited in place.**  The promise *"`connect()` happens inside the factory — the returned socket is already connected"* is retired entirely: the connector is the only connect implementation (Decision 0098) and it is non-blocking by contract.
- **Decision 0051's runner-shaped rule list grows by one bullet.**  In addition to `time.sleep(N > 0.005)` and `select.poll(timeout > 0)`, library methods that perform network I/O don't block — including connect.  Non-runner contexts drive the connector to terminal inline instead of reaching for a blocking form.
- **Implementation is tracked separately** in [`plans/workstreams/archive/non-blocking-connect-implementation.md`](../workstreams/archive/non-blocking-connect-implementation.md).  The workstream covered the connector contract, per-runtime substrate handling (CPython EINPROGRESS / MP rp2 / CP socketpool's blocking compromise), `MQTTClient`'s state-machine migration, and the `chumicro-requests` / `chumicro-websockets` migrations.  Phases 1.1, 1.2, 1.3, 2, 4, and 5 shipped; Phase 6 (http-server) was deferred.
- **The runner-shaped policy clarification cascades.**  Library audits (`/audit-embedded chumicro_mqtt`, `/audit-library chumicro_sockets`) should flag any other library method that does synchronous network I/O.  Likely candidates: chumicro-ntp's `query`, chumicro-wifi's `connect` (separate ADR scope; not in this one).
