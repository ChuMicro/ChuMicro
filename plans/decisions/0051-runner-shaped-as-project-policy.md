# Decision 0051: Runner-shaped is project-wide policy, not just `chumicro-runner`

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0014 (runner pattern as the contract), Decision 0010 (constructor injection), Decision 0042 (library dependency policy).

## Context

Decision 0014 introduced the gate-based runner pattern (`check(now_ms) -> bool` + `handle(now_ms)`) inside `chumicro-runner`.  In practice, every downstream chumicro library that owns time or I/O — `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`, `chumicro-wifi`, `chumicro-ntp` — implements the same contract.  This is what makes "the LED keeps blinking through a TLS handshake" possible: nothing in the library blocks the main loop.

But Decision 0014 framed the contract as a chumicro-runner concern.  The cross-cutting rule — *every* library obeys the contract — is enforced by review and tracemalloc tests, but isn't named as a project-level policy.  A contributor proposing a synchronous library would discover the rule from review feedback rather than from a documented commitment.

## Decision

Every chumicro library that owns time, I/O, or any operation that could take more than a few ms must be **runner-shaped**.

Two acceptable shapes:

1. **Long-lived service:** exposes the runner contract — `check(now_ms) -> bool` + `handle(now_ms)`.  The application's main loop calls `check`; if it returns true, the application calls `handle`.  All work is incremental — one chunk of read, one chunk of write, one state-machine step per `handle` call.
2. **Per-tick chunked progression:** an internal state machine that progresses one chunk per outer-loop iteration.  Examples: `chumicro-deploy`'s CP RAM-mode chunked send, `chumicro-mqtt`'s in-flight QoS 1 tracker.  This shape is appropriate for libraries that don't need the application to drive them tick-by-tick but still must yield often enough that the LED doesn't stutter.

The contract is **duck-typed**.  Libraries do NOT need to import or subclass anything from `chumicro-runner`.  An application that orchestrates services manually (without `chumicro-runner`) gets the same blocking guarantees.

Forbidden in library code (any of `libraries/*/src/`):

- `time.sleep(N)` for `N > 0.005`.  Short sleeps (e.g., 1 ms USB-CDC settle) are acceptable when documented.
- `select.poll(timeout > 0)` in a leaf service.  A library's own `check`/`handle` code uses `timeout=0` and re-polls on the next tick; it must never block the loop.  The one exception is the runner's single central wait (`Runner.wait`, called once per loop iteration by the application), which *may* block until the next deadline — it is the loop idling, not a service stalling it.  See [Decision 0080](0080-runner-reactor.md).
- Synchronous DNS resolution that doesn't yield (some MP DNS calls block ~5 s on timeout).
- Any function that can wait on the network without a tick-bounded budget knob.

These rules apply to libraries.  Workbench packages (`workbench/*/`) run on CPython and have looser constraints — a `chumicro-deploy` flash-mode rsync legitimately blocks for seconds.

## Rejected

**Async / await as the cross-cutting model.**  Not a support claim — all three runtimes ship a usable `asyncio` on the boards we target.  The rejection is that an event loop is the wrong *shape* for this class of device, on two grounds:

- **Transparency on a board where serial is your only window.**  The runner contract is a plain `while True:` the developer can read, breakpoint, and single-step; scheduling is explicit in the caller's loop.  An event loop hides where a task yields, turning "why did the LED stutter" into scheduler archaeology with no profiler to fall back on.  This is the framing the README and `chumicro-runner`'s own README already rest on; this ADR aligns with them.
- **The non-blocking guarantee doesn't survive the asyncio socket layer.**  The whole point is "nothing blocks the main loop."  But MicroPython's asyncio still resolves names through a blocking `getaddrinfo` (documented in its own asyncio reference), so an `await`-ed connect can still stall the loop — the project would have to layer the same non-blocking-DNS / chunked-yield machinery the runner already provides *on top of* asyncio to get the guarantee.  The event loop adds a scheduler whose task ordering is less predictable, for no net gain over the explicit tick.

Decision 0014 rejected this; we re-affirm on shape, not capability.

**`time.sleep()` is allowed if it's "short enough."**  Rejected: every project that allows "short enough" sleeps drifts to seconds eventually.  Hard rule with documented exceptions stays enforceable.

**Run a thread-pool internally.**  Threads are unavailable on most embedded ports and add memory cost on the rest.  The runner-shaped contract gives equivalent yielding behavior using cooperative scheduling.

## Consequences

- Library code reviews include a "does any path block more than a few ms?" check.  Blocking paths get flagged for rework or a documented exception (workstream-level discussion + a doc comment).
- Tracemalloc-based heap-drift tests (established by `chumicro-mqtt`) become the standard verification — every long-lived service library has a heap-stability test under `tests/`.
- New libraries that own time or I/O document their per-tick budget knobs (e.g., `recv_budget_per_tick`, `max_tx_queue_size`) up front.
- The runner library (`chumicro-runner`) is still optional for users who orchestrate services manually; the contract the runner consumes is duck-typed and works either way.
- This rule is what gives "LED keeps blinking" its teeth.  Without it, the project's ergonomic promise breaks.
