# Decision 0102: `Runner.run_until` drives bounded loops on the runner

Status: `accepted`
Date: `2026-07-04`
Summary: `Runner.run_until` ticks and waits until a generator handle finishes or a predicate is truthy, re-raising `handle.error` on task death; it drives bounded waits, not the application's main loop.
Related: Decision [0014](0014-runner-pattern.md) (the runner contract), Decision [0080](0080-runner-reactor.md) (the central `wait()` — the loop's two beats), Decision [0087](0087-generators-for-sequential-io.md) (`add_generator` / `GeneratorHandle` and task-fault isolation), Decision [0088](0088-periodic-phase-anchoring.md).

## Context

Every demo and every bounded drain hand-rolls the same tail loop — `while not done: runner.tick(); runner.wait()` — since Decision 0080 makes `tick()` then `wait()` the loop's two beats. Copied by hand, each instance risks getting the wait, the timeout, or the error handling subtly wrong. `run_until` (runner 0.11.0, git `59e7d8ab`, "demos lose their tail loops") collapses it into one call. Neither Decision 0014 nor 0080 records it.

## Decision

`run_until` is a convenience on `Runner` that ticks once, then loops: check the completion condition, check the timeout, idle in `wait()` until the next event or deadline. It accepts one of three forms:

- **a generator handle** (anything exposing `done`) — run until the task finishes; if the task died, `handle.error` is re-raised from `run_until`.
- **a zero-argument predicate** — return `True` once it is truthy after a tick.
- **`None` with a `timeout_ms`** — the "run for this long" form, a drain window (a QoS-ack flush) that returns `False` at the deadline.

- **Loud failure is the point of the handle form.** A generator task that raises is isolated by the runner (Decision 0087) and stored on its handle; the loop does not crash. In a demo that would mean sailing past a dead task and exiting clean — a silent pass. The handle form re-raises `handle.error` so the demo exits non-zero instead.
- **Bounded, not the main loop.** `timeout_ms` is best-effort: it is re-checked only when an event wakes `wait()`, so a hard bound needs a deadline source (a periodic task, a connector). `run_until` owns a loop only for a *bounded* wait with a completion condition; the application's own `while True:` stays hand-written and single-steppable. This is why it is not the `Runner.run()` that Decision 0080 rejects — that would hide the unbounded main loop and forfeit the read-and-breakpoint transparency the runner pattern protects.
- **On the runner, not in app code.** The tick-then-wait shape is the runner's contract, not the caller's. Folding the loop, the timeout arithmetic, and the error re-raise into one method keeps every demo and drain from re-deriving them and drifting.

## Rejected

- **`Runner.run()` owning the app loop** — forfeits transparency (Decision 0080); `run_until` stays bounded and returns control.
- **A raw `while` in every demo** — duplicates the wait / timeout / error semantics N times; this is the boilerplate `run_until` replaced. Teaching code is the exception: demos and examples pay that duplication on purpose so the loop stays on the page — see [Decision 0122](0122-demos-and-examples-write-the-loop-out.md).
- **Swallowing `handle.error`** (returning `False` on task death) — hides the failure the handle form exists to surface.

## Consequences

- Bounded drains in application code are one call: `handle = runner.add_generator(...); runner.run_until(handle)`. Demos and examples write that loop out instead ([Decision 0122](0122-demos-and-examples-write-the-loop-out.md)).
- The main application loop is unchanged and still owns its `while True:`.
- `run_until` adds no new blocking primitive — it composes `tick()` and `wait()`, so the tick-budget and no-async rules (Decisions 0080/0087) hold unchanged.
- A timeout is only as tight as the runner's nearest deadline source; a caller wanting a hard bound registers one.
