# Workstream: runner/task API design pass (M49 + M51 + M31 + factory shape)

Status: **awaiting user verdicts** (2026-07-03).  The four escalated design questions from the
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
