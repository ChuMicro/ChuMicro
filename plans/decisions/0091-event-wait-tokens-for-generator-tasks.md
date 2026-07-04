# Decision 0091: Event-wait tokens for generator tasks

Status: `accepted`
Date: `2026-07-02`
Summary: Generator waits gain a `ready(now_ms)` predicate plus a `Signal` token (home: `chumicro_timing.waits` per 0095); bare `yield` resumes next tick; `Runner.wait` parks when no deadline exists.
Related: 0087 (generator substrate), 0089 (generator surfaces on networking libraries), 0080 (runner reactor)

## Context

The generator substrate can suspend on two things: a socket event and a deadline. A completion that originates in callback-land — a wifi link coming up, any one-time setup another service signals — cannot suspend a generator, so sequential flows that gate on one fall back to a state-change callback plus a module-level flag, the shape Decision 0089 identifies as advertising the wrong pattern. Two adjacent substrate gaps compound it: a bare `yield` sends `None` into the wrapper's finished-slot, silently wedging the task forever, and `Runner.wait` returns immediately when only socket-driven services are registered, busy-spinning the loop at full CPU instead of parking.

## Decision

### 1. The wait protocol gains an optional `ready(now_ms) -> bool`

A yielded wait with no socket may expose `ready(now_ms)`. The wrapper resumes the generator when `ready` returns True, or when the wait's `next_deadline` elapses (the timeout path). A not-ready wait with no elapsed deadline stays suspended. Socket-driven waits and plain deadline waits keep their shipped behavior.

### 2. A bare `yield` means "resume next tick"

`yield` with no value suspends for exactly one tick. Internally the wrapper maps the `None` send-result to a module-level next-tick wait; a cleared wait slot strictly means the generator finished.

### 3. `Signal` and `wait_for` live in `chumicro_timing.waits`

Originally landed in `chumicro_runner.generators`; [Decision 0095](0095-timing-wait-vocabulary.md) moved both into `chumicro_timing.waits` (runner consumes them; `sleep_until` stayed in runner).

`Signal` is a one-slot completion token: `set(value)` / `clear()` / `is_set` / `value` / `ready(now_ms)`. Setters are plain callables, so any callback-style service can complete one. `wait_for(signal, deadline_ms=...)` suspends until the signal is set and returns its value, raising `OSError(ETIMEDOUT)` past the optional deadline. Tokens are reusable across waits; a suspended wait allocates nothing per tick.

Scope follows Decision 0089's invariant: `yield from` is for sequential awaits of a result the flow genuinely blocks on. `Signal` serves one-time completions (link-up, handshake-finished); reactive fan-out and fire-and-forget acks stay callbacks, and no library grows a generator verb this decision's tokens would smuggle past 0089's rejections.

A signal wait contributes no wake timeout of its own. In the cooperative model a signal can only be set from another service's tick, so the setting service's own wake source (socket or deadline) is what gates `Runner.wait` — the loop cannot deadlock on a signal that something registered can still set.

### 4. `Runner.wait` parks when only socket-driven services are registered

With sockets registered and no deadline anywhere, `wait` blocks in the poller indefinitely (`ipoll(-1)`) instead of returning immediately. The early return remains only when a deadline is already due, or when there is neither a socket nor a deadline to wait on. This makes `SocketConnector.next_deadline`'s documented "``None`` here lets the runner's ``wait`` park indefinitely" contract true and lets purely socket-driven applications idle the CPU.

## Consequences

- `chumicro_runner` minor bump: `Signal` + `wait_for` are new public API; the wrapper's `check()` consults `ready()`; `wait` gains the indefinite-park branch.
- The wifi-then-start preamble in board apps can collapse into the generator body (`yield from wait_for(link_up)`), removing the callback-plus-global wiring.
- Poll registration now actually happens for no-deadline socket waits, so wrapper objects that are not pollable surface immediately instead of being masked by the busy-spin — the `.sock`-exposing wait shapes in `chumicro_sockets.generators` are what keeps that registration valid.

## Rejected

- **`result(now_ms)` send-value protocol** (0087's original sketch). A second dispatch per resume, and a per-wait value plumbed through the wrapper, to save one attribute read (`signal.value`) after resuming. The wrapper keeps sending `now_ms` — generators doing deadline math need it, and it allocates nothing.
- **Named `ReadReady` / `WriteReady` / `Sleep` token classes.** The shipped duck-typed attributes already cover sockets and deadlines; adding named classes for the same semantics is API surface without capability.
- **`Signal` in runner core.** Keeping it out of core (first the opt-in `generators` module, now `chumicro_timing.waits` per Decision 0095) means plain check/handle consumers load none of it.
- **Predicate-polling waits** (`yield until(lambda: ...)`). Resuming to evaluate arbitrary predicates every tick is a busy-poll with extra steps; a set-once token makes the completer explicit and allocation-free.
- **Per-library `connected()`-style verbs built on `Signal`.** Decision 0089 already rejected these for MQTT; the token is substrate, and whether any library earns a verb remains a 0089-invariant question decided per library.
