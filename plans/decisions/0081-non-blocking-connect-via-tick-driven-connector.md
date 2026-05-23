# Decision 0081: Non-blocking connect via a tick-driven connector

Status: `proposed`
Date: `2026-05-23`
Related: Decision 0014 (runner contract), Decision 0031 (chumicro-sockets factories — partially superseded), Decision 0051 (runner-shaped as project policy), Decision 0080 (runner reactor / central wait)

## Context

`chumicro-sockets` today exposes synchronous factories that perform DNS, TCP connect, and the TLS handshake inline before returning a connected socket (`_adapters/cp.py:65`, `_adapters/mp.py:121`, `_adapters/cpython.py` analog).  Decision 0031 §2 makes this an explicit promise: *"`connect()` happens inside the factory — the returned socket is already connected.  Callers do not see a disconnected socket or a separate connect step."*

That promise predates Decision 0080's central-wait carve-out and Decision 0051's runner-shaped rule.  The rule says a leaf service must never block the loop; the only sanctioned blocking point is `Runner.wait`.  But `chumicro_mqtt.MQTTClient.connect()` and `_attempt_self_heal()` both call `socket_factory()` synchronously, which can spend seconds in DNS + TCP + TLS.  Self-heal is the egregious case (it runs INSIDE `handle()`, stalling every other registered service for the duration of a wifi-up-DNS-resolve-TCP-connect-TLS-handshake cycle), but the user-facing `connect()` is symmetrically broken: if any caller invokes it from inside a runner-tick handler (button press, state-machine event, lazy-connect-on-demand), it stalls the loop the same way.  "Call `connect()` from main before the runner loop starts" is a convention, not a contract — and a convention isn't enough when the runner-shaped rule says libraries don't block.

The reference impl (`~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`) handles reconnect entirely in user space: `loop()` raises on a dead connection, the application catches it and calls `start_connect()` from `main`.  This makes the library's loop guarantee strict (loop never blocks) at the cost of pushing reconnect logic onto every caller.  chumicro made the opposite tradeoff in Decision 0031 + the self-heal addition: convenient automatic reconnect at the cost of the runner-shape violation.  The 2026-05-23 convergence session validated steps 1-6 of the runner-friendliness fixes (commits `5fe9182d` through `7c5bff6f`); the connect path is the remaining gap.

## Decision

### 1. Library methods that perform network I/O don't block

Generalizing Decision 0051's runner-shaped rule: any library method that performs network I/O — including DNS resolution, TCP connect, TLS handshake — yields to the runner between phases.  The convention "callers invoke connect outside the loop" is not a substitute.  The library's contract is "this call returns in bounded time" and bounded means under the runner's tick budget (~5 ms), not "however long the network takes."

### 2. `chumicro-sockets` exposes a tick-driven connector for non-blocking connect

Two new sibling factories complement the existing synchronous ones:

```python
tcp_client_connector(host, port, *, radio=None) -> SocketConnector
tls_client_connector(host, port, *, context=None, radio=None) -> SocketConnector
```

`SocketConnector` is a tick-driven state machine.  Each call to `connector.tick(now_ms)` advances one phase; phases that require network I/O return immediately if their underlying socket would block, and the connector exposes `io_socket` / `io_wants_read` / `io_wants_write` / `next_deadline` so the runner can park in `Runner.wait` until POLLIN / POLLOUT / timeout fires.

```python
class SocketConnector:
    state: str  # "awaiting_dns" | "awaiting_tcp" | "awaiting_tls" | "ready" | "failed"
    socket: TCPClientSocket | None  # Set when state == "ready"; None otherwise.
    last_error: Exception | None    # Set when state == "failed".

    # Runner-contract surface (same shape as any I/O service).
    io_socket: object | None
    io_wants_read: bool
    io_wants_write: bool

    def tick(self, now_ms: int) -> None: ...
    def next_deadline(self, now_ms: int) -> int | None: ...
    def cancel(self) -> None: ...  # Close any in-flight socket, transition to "failed".
```

The connector itself can be registered with `Runner.add()` as an object-based task with `.check()` returning `True` while `state` is non-terminal and `.handle()` calling `.tick()`.  In practice, the consumer library (chumicro-mqtt, etc.) embeds the connector in its own state machine rather than registering it directly.

### 3. Per-runtime substrate handling

The three runtimes diverge on what non-blocking-connect primitives are available; the connector contract papers over the divergence:

- **CPython**: stdlib `socket.connect()` on a non-blocking socket raises `BlockingIOError` (EINPROGRESS).  `select.poll(POLLOUT)` + `getsockopt(SO_ERROR)` reports completion.  TLS via `ssl.SSLContext.wrap_socket(do_handshake_on_connect=False)` + a loop calling `sock.do_handshake()` and catching `SSLWantReadError` / `SSLWantWriteError`.
- **MicroPython** (rp2 lwIP, esp32): non-blocking `socket.connect()` raises `OSError(EINPROGRESS)`.  `select.poll(POLLOUT)` checks completion.  TLS via `ssl.wrap_socket` is on most ports BLOCKING — `MICROPY_SSL_MBEDTLS` does the handshake inline.  Where the port doesn't support non-blocking TLS handshake, the connector's `awaiting_tls` phase BLOCKS for the handshake duration in `tick()` and the connector documents this substrate limit.
- **CircuitPython** (`socketpool`): `Socket.connect()` is synchronous; `socketpool` does not expose a non-blocking-connect path.  The connector's `awaiting_tcp` phase BLOCKS on CP — substrate limit, documented on the connector and in the platform-support matrix.  TLS via `radio.TLS_MODE` is similarly synchronous.

This is a real platform-specific reality: on MP+CPython the connector can be truly non-blocking; on CP, the connector's `tick()` blocks for one phase per call but at least breaks the work across phases (DNS in tick N, TCP+TLS in tick N+1) and crucially never blocks while the runner expects bounded handle() time.

A future amendment may add non-blocking CP support if a future CircuitPython release exposes the primitives.  The connector contract is forward-compatible.

### 4. `chumicro-mqtt` consumes the connector via its existing state machine

`MQTTClient` gains two new `ProtocolState` variants (`AWAITING_TRANSPORT`, plus the existing `CONNECTING` semantics narrow to "MQTT CONNECT packet in flight, awaiting CONNACK"):

- `DISCONNECTED → AWAITING_TRANSPORT`: `connect()` constructs the connector via the configured connector-factory and stores it.
- `AWAITING_TRANSPORT → CONNECTING`: `handle()` calls `connector.tick(now_ms)`; when `connector.state == "ready"`, the underlying socket moves to `self._socket`, the connector is dropped, and the MQTT CONNECT packet is queued.
- `AWAITING_TRANSPORT → FAILED`: connector reports `state == "failed"`; `last_error` carries the connector's reason.
- `CONNECTING → CONNECTED`: existing CONNACK handling, unchanged.
- `_attempt_self_heal` constructs a fresh connector and transitions to `AWAITING_TRANSPORT` — no separate self-heal code path; the connect state machine handles both initial and re-connect.

`connect()` returns immediately (no network I/O on the caller's thread).  All I/O happens in subsequent `handle()` ticks.  Calling `connect()` from inside a runner-tick handler is safe.

### 5. The synchronous factory stays for one-shot / non-runner contexts

`tcp_client_socket()` and `tls_client_socket()` remain.  They're still useful for one-shot scripts, REPL exploration, tests that want a fully-connected socket immediately, and any code that genuinely owns the loop (e.g. a `main` that does setup before entering the runner loop).  Library code that's runner-shaped — anything under `libraries/` that registers with a Runner and exposes `check`/`handle`/`io_*` — uses the connector form exclusively.

This is the same shape Decision 0080 took for blocking poll: the leaf rule bans `poll(timeout > 0)`, the central-wait carve-out allows it in `Runner.wait`.  Here: the leaf rule bans synchronous network I/O in library methods, the synchronous factory is the carve-out for non-runner callers.

## Rejected

- **EINPROGRESS-style "partially-connected socket" return.**  Factory returns a raw socket mid-connect, caller polls POLLOUT + checks SO_ERROR.  Rejected because it offloads the TLS handshake state machine onto every caller, and chumicro-mqtt, chumicro-requests, chumicro-websockets, chumicro-http-server would each reimplement it.  The connector object owns the handshake state once, in one place.
- **Async / await across runtimes.**  Decision 0080 §Rejected covers this in detail — coroutine-bound I/O reactor is incompatible with the tick-based runner; same reasoning applies to non-blocking connect.
- **Removing self-heal entirely (the reference's pattern).**  Considered: `loop()`-raises-on-dead-connection + caller-handles-reconnect is the reference's chosen tradeoff (`~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`).  Rejected because chumicro's runner-shaped model is "the library tells the runner what it needs (`io_*`, `next_deadline`) and the runner gives it time slots."  Pushing reconnect onto application code violates that model — the application would have to inspect `state == FAILED`, re-call `connect()`, and re-add to the runner.  The connector pattern keeps reconnect inside the library while fixing the blocking problem.
- **Per-runtime "fake" non-blocking on CircuitPython** (spawn a thread, do the synchronous connect there, fake the connector interface).  Rejected because CP doesn't have threads and the patterns we'd need to fake (separate task, callback-on-complete) don't exist on the substrate.  CP's substrate limit is what it is; the connector's per-phase blocking on CP is the honest answer.
- **Folding the connector into the synchronous factory** ("factory returns a connector with `tick()` called inline if `blocking=True`").  Rejected because the two surfaces are different by design — one returns an object you tick, the other returns a connected socket.  Conflating them confuses the call site about whether work has happened yet.

## Consequences

- **Decision 0031 §2 is edited in place.**  The promise *"`connect()` happens inside the factory — the returned socket is already connected"* now applies only to the synchronous factories; the new connector-form factories are non-blocking by contract.  The §2 paragraph names both forms and which is appropriate when.
- **Decision 0051's runner-shaped rule list grows by one bullet.**  In addition to `time.sleep(N > 0.005)` and `select.poll(timeout > 0)`, library methods that perform network I/O don't block — including connect.  The carve-out is the synchronous factories under `chumicro_sockets` for non-runner contexts.
- **`chumicro-sockets` gains `tcp_client_connector` / `tls_client_connector` + `SocketConnector`.**  Per-runtime adapters implement the substrate-specific connect/handshake machinery, documenting where the substrate doesn't support true non-blocking.
- **`chumicro-mqtt.MQTTClient.connect()` becomes non-blocking.**  No network I/O on the caller's thread.  `AWAITING_TRANSPORT` state added.  Self-heal restructured to use the connector path.
- **`chumicro-requests`, `chumicro-websockets`, `chumicro-http-server`** must be migrated to the connector form too.  Each currently uses the synchronous factory; the migration is per-library but mechanical.  Tracked in `plans/next-up.md` as separate items.
- **FakeSocket-equivalent connector for tests.**  `chumicro_sockets.testing` gains a `FakeSocketConnector` that scripts the state-machine transitions deterministically — same pattern as `FakeSocket` for the synchronous side.
- **CircuitPython's per-phase blocking is documented loudly.**  The connector's docstring and platform-support matrix say "on CP, `awaiting_tcp` and `awaiting_tls` block for one phase each."  Callers expect roughly DNS-time + TCP-connect-time + TLS-handshake-time across three ticks instead of all-at-once — better than the current all-blocking-in-one-tick situation, but not yet the true non-blocking shape MP+CPython get.
- **Bake-validate against the negative-bake suite** (`plans/workstreams/mqtt-negative-testing-suite.md` A1-E3).  The connector pattern's value is that broker-disconnect + self-heal doesn't stall the runner mid-reconnect.  A1 (broker hard-kill + restart) is the foundational validation.
- **The runner-shaped policy clarification cascades.**  Library audits — `/audit-embedded chumicro_mqtt`, `/audit-library chumicro_sockets` — should flag any other library method that does synchronous network I/O.  Likely candidates: chumicro-ntp's `query`, chumicro-wifi's `connect` (separate ADR scope; not in this one).
