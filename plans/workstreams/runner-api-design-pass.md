# Workstream: runner/task API design pass (M49 + M51 + M31 + factory shape)

Status: **verdicts in** (2026-07-03): M49 = both surfaces (shipped, runner 0.14.0); M51 =
**full break** — superseded by Decision 0092 (no pre-publication backwards compat): the
callable-check shape and the second `next_deadline` convention are deleted outright, all
consumers migrated in the same commit; `add_periodic` stays on teaching merit (it is sugar,
not compat).  Factory = one contract, local copies (decided).  M31 = **shipped** (mqtt 0.20.0
`next_message()` + 0089 amended in place, 2026-07-03).  M51 shipped with the 0092 removal
wave.  Section 4 shipped as Decision 0093 + ntp 0.11.0 (deferred open).  **All four items closed 2026-07-03.**  The four escalated design questions from the
straggler fan-out, with options and a recommendation each.  All four reshape public surfaces the
demos teach, so they get decided together, with the user, before any code.

## 1. M49 — where does a dead task's error go?

A generator task that raises today just flips `handle.done`; the 2026-07-03 websockets bake
burned a 30 s diagnosis on exactly that silence.

- **(a) `handle.error` attribute** — the wrapper stores the exception; `done` stays the loop
  signal; drivers check `handle.error` after the loop.  Zero new callback plumbing, zero
  steady-state cost, but silent unless the caller looks.
- **(b) `on_task_error` runner hook** — one global callback (mirrors the existing
  `_on_handler_error` shape).  Loud by default when wired; apps must wire it.
- **(c) both** — store on the handle always; optional global hook for apps that want a log line.

**Recommendation: (c).**  The pair costs one attribute and one `if`; (a) alone repeats the
silent-by-default failure this item exists to kill, (b) alone loses per-task attribution.

## 2. M51 — registration-shape consolidation

Four shapes (`add`, `add_periodic`, callable-check, `add_generator`) and two same-named but
incompatible `next_deadline` conventions.

- **(a) collapse to two** — `add(service)` (duck-typed object, one documented `next_deadline`
  contract) and `add_generator(gen)`; `add_periodic` becomes a thin documented alias; the
  callable-check shape is deprecated in docs, kept working.
- **(b) full break** — remove the redundant shapes at a major bump.

**Recommendation: (a).**  The audit's complaint was *learning cost*, not code weight; two
documented front doors plus quiet aliases fix the docs without breaking every consumer.  Decide
the single `next_deadline` convention here (absolute tick deadline, the connector convention) and
adapt the other in-place.

## 3. M31 — mqtt blocking/pump facade

Every mqtt consumer hand-rolls tick loops and mutable-cell lambdas for one-shot flows.

- **(a) `client.pump(runner=None, until=..., timeout_ms=...)`** — a loop facade over
  check/handle, mirroring `Runner.run_until`'s shape.
- **(b) generator surface** — contradicts ADR 0089's recorded decision (mqtt stays reactive;
  re-opening 0089 needs stronger evidence than convenience).
- **(c) do nothing** — `Runner.run_until` (shipped) already collapses most of the demo pain.

**Recommendation: (c), revisit after the demos settle.**  The M31 finding predates `run_until`
and the demo rewrites; the remaining hand-rolling is small, and (a) would add a second blessed
loop idiom for the same job the runner now owns.  Cheap to reverse if real apps still hurt.

**2026-07-03 analysis of whether ADR 0089's mqtt paragraph still holds** (requested at the
verdict gate).  0089 rejected two specific shapes: `yield from mqtt.publish_acked(...)` — still
right, QoS acking is internal bookkeeping nobody should block on — and
`yield from mqtt.connected()`, whose stated rationale ("one-time setup better served by an
on_connect callback") has aged: ADR 0091's `Signal`/`wait_for` post-dates it and already gives
any app a linear connect-wait in three lines with zero mqtt API (`client.on_connect` sets a
Signal; the generator does `yield from wait_for(connected)`), exactly how the demos now wait for
wifi.  What 0089 never evaluated is the **receive-stream** flavor for mqtt — its own blessed
flavor 2.  A single-subscription command consumer is structurally identical to websockets'
`next_message()` (which shipped, baked, and reads well): a bounded inbound queue on the client
plus `message = yield from client.next_message()`, with the callback fan-out surface unchanged
for multi-topic apps — the same dual surface websockets kept.  Unlike the connect-wait, this one
cannot be built from 0091 primitives (inbound payloads must queue inside the client), so it is a
genuine library surface, not sugar.  **Refined proposal:** amend 0089's mqtt paragraph narrowly —
mqtt gains the receive-stream flavor only (`next_message()`, bounded queue, drop-oldest, mirroring
websockets' design and knob); connect stays reactive (0091 covers linear waits); publish/subscribe
stay fire-and-forget (the rejected `publish_acked` stays rejected).  Design questions if adopted:
one global inbound queue vs per-subscription; interaction with pattern handlers on first use.

## 4. Factory/from_config shape (M77 + ntp L52/L53)

Five diverging `sockets_factory` copies, three contracts; ntp opens its socket eagerly at
construction while mqtt/http_server defer to first tick.

- **(a) one blessed contract, five local copies** — decide the invariants (factory signature
  `(host, port, use_tls) -> connector`; construction is side-effect-free; `from_config` stays a
  classmethod; transports open on first tick) and align each library in place.  Copies stay
  copies (per-library deploys must not gain a shared dependency).
- **(b) promote a shared `chumicro_factories` library** — kills the duplication but adds a
  dependency edge to every networking library and another package on flash.

**Recommendation: (a).**  The duplication is ~65 lines/library and deploy-graph-friendly; the
*divergence* is the bug.  ntp aligns to deferred-open (its L52/L53 escalations resolve under the
same invariant); an ADR records the contract so the copies can't drift again.

## Already landed without needing verdicts

- Runner-side `.sock` unwrap (runner 0.13.0) — the `io_socket` contract is now "socket-ish;
  the runner unwraps", producers freed; demos L9's unwrap half resolved.
- Board-side `marker()` helper (`chumicro_test_harness.markers`, 0.3.0) — whitespace/`=`-free
  marker values are structural now; all seven demos adopted it; harness `__init__` went
  PEP-562 lazy so the helper doesn't drag the runner machinery onto flash.
