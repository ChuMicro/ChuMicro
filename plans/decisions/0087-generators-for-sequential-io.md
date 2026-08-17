# Decision 0087: Generator-driven coroutines for sequential I/O

Status: `accepted`
Date: `2026-05-25`
Summary: Sequential I/O state machines use generator functions (`def` + `yield from`) registered via `runner.add_generator()`; `async`/`await` and the `asyncio` module are both banned in library code.

Related: Decision 0014 (runner pattern), Decision 0051 (runner-shaped policy), Decision 0080 (runner reactor), Decision 0081 (non-blocking connect via tick-driven connector)

## Context

The runner-shaped contract from Decisions 0014 / 0051 (`check(now_ms) -> bool` + `handle(now_ms)`, plus the `io_socket` / `io_wants_read` / `io_wants_write` attributes added by 0080) reads cleanly for reactive services — MQTT keepalive, WiFi state changes, button debounce, sensor polls — but is verbose for sequential I/O state machines. The `demos/sockets_runner_connector/app.py` `EchoService` is the canonical case: ~80 lines of explicit state machine — four state strings, three `_handle_*` methods, manual `_send_offset` tracking, three `io_wants_*` properties — for what is conceptually "connect, send, recv, close." A first-time custom-protocol author bounces off the ceremony.

Decisions 0051 and 0080 both rejected adopting asyncio, but the rejection elided a load-bearing distinction. Two independent things sit under "async" — the **asyncio module** (an event-loop scheduler + a stream layer + a Task heap) and the **language-level coroutine substrate** (generator `.send()` / `.throw()` / `.close()`, `yield from` for delegation, PEP 380 return-value semantics). The module-level scheduler is the part incompatible with the runner reactor. The generator substrate is just Python's cooperative-scheduling primitive; trio and curio drive their own schedulers on top of it on CPython, and the same approach works on MP and CP today.

Two further pieces of runtime evidence sharpen the choice of *syntax* once the substrate is settled:

- The asyncio module itself remains a poor substrate to depend on. Adafruit's CircuitPython port (the only path to asyncio on CP) has [issue #4](https://github.com/adafruit/Adafruit_CircuitPython_asyncio/issues/4) open since 2021-11-18: `asyncio/stream.py` imports `usocket`, a MicroPython-only module not present on CircuitPython, so `asyncio.open_connection` / `start_server` / `StreamReader` / `StreamWriter` are all broken on CP. Recent commits to the repo are upstream-sync, not bug-fix.

- `async`/`await` and `yield from` are **not** byte-identical on CircuitPython. MicroPython compiles `await x` directly to `YIELD_FROM` (MP `py/compile.c:2767-2780`); CircuitPython explicitly diverges and emits `load_method __await__; call; YIELD_FROM` (CP `py/compile.c:2790-2796`, with an in-source `// CIRCUITPY-CHANGE: Use __await__ instead of yield from.` comment). On CP, every `await` costs a method dispatch plus a fresh generator instance from the `__await__()` call. `yield from` is one bytecode on both runtimes. MP's compiler is also the direct proof that `await` is a wrapper over the generator substrate: `compile_atom_expr_await` is `compile_atom_expr_normal` followed by `compile_yield_from` and nothing else.

- The asyncio engine is real machinery with a real footprint. The standard MicroPython build freezes `extmod/asyncio` into firmware: 1,046 lines of Python (core.py 324, stream.py 222, task.py 177, funcs.py 145, plus event/lock/init glue), flash spent whether or not the application imports it. Every running coroutine is wrapped in a `Task` carrying pairing-heap link fields (`extmod/asyncio/task.py:4` and `Task.__init__`), the scheduler resumes whatever the heap yields next (deadline keys, then I/O-poll wake order) rather than anything registration-ordered, and `run_until_complete` owns the `while True` (`core.py:152`), which is the loop-ownership conflict with the runner stated in one line. The engine even has to dodge its own allocation hazards in-loop (`core.py:154-155`, "To prevent heap allocation in loop"). The runner's contrast is direct: `Runner.tick()` sweeps `self._entries` in registration order (`chumicro_runner/core.py`, the `for entry in self._entries` loop) and its pending list holds at high-water capacity precisely to avoid a per-tick re-grow allocation.

## Decision

### 1. Sequential I/O uses generator functions

Library code expresses sequential I/O state machines as **generator functions** registered with the runner via `runner.add_generator(gen) -> GeneratorHandle`. The generator suspends by `yield`-ing a duck-typed wait object — anything exposing `io_socket` / `io_wants_read` / `io_wants_write` / `next_deadline`, or the event predicate `ready(now_ms)` added by [Decision 0091](0091-event-wait-tokens-for-generator-tasks.md). The runner reads those each `wait()` to register the socket with ipoll, and resumes the generator via `.send(now_ms)` once the socket is ready, the deadline elapses, or the event fires. The runner's external dispatch surface is unchanged — internally the wrapper satisfies the same check/handle/io_* contract everything else does.

```python
from chumicro_sockets import tcp_client_connector
from chumicro_sockets.generators import connect, recv_until, send_all

def echo_run(connector):
    sock = yield from connect(connector)
    try:
        yield from send_all(sock, b"hello chumicro\n")
        reply = yield from recv_until(sock, b"\n", max_bytes=4096)
    finally:
        sock.close()

handle = runner.add_generator(
    echo_run(tcp_client_connector(host, port, radio=wifi.adapter.radio)),
)

while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

### 2. `async`/`await` syntax and the asyncio module are both banned

CHU033 fails on `async def`, `await`, `async with`, `async for`, `import asyncio`, `from asyncio import …`, and `import uasyncio` in `libraries/`, `support/`, and `workbench/`, excluding `functional_tests/` — those are host-only, hardware-driving test servers that may reach asyncio through a host package (the websocket echo server does). The check is AST-based, so the same keywords inside a string literal — a boot shim that *rejects* `async def run` — are not flagged.

### Why generators, not async/await

Four reasons, in declining order of weight:

1. **Yield-point hygiene.** Every `yield` / `yield from` is a scheduler checkpoint — a place the runner gets to interleave another service's work between two lines of your code. With `async def` + `await`, the natural pattern is to write `await` in front of every helper call, including helpers that do pure CPU work. The asyncio community has a name for the result ("coroutine-without-await") and a class of linters that try to catch it after the fact. With `def` + `yield from`, you *cannot* `yield from` a regular function — it raises `TypeError`. The syntax enforces the invariant that every `yield from` corresponds to a helper that actually suspends; pure-CPU helpers stay regular functions and can't accidentally be promoted by anyone reaching for the wrong keyword. On a 256 KB device where the runner's whole value prop is "every other service runs between your yields," the marker semantics matter more than the keyword familiarity. Fewer, deliberate suspension points also shrink the interleaving surface: every yield is a window where every other service's effects can land between two of your lines, so sprinkled `await`s multiply the schedules a device can exhibit, and the bugs that appear under only one of them.

2. **Transparency and determinism.** A `yield` is one bytecode that hands control to the scheduler — single-steppable, breakpoint-able, visible in a traceback. `await` hides the same handoff behind compile-time machinery that *differs per runtime*. The runner's README leans on "the developer can read, breakpoint, and single-step"; the more transparent primitive matches the project's posture. The scheduling around the pause is also more predictable: the runner resumes work in registration order on every tick, while an asyncio loop resumes whatever its task heap yields next (see the runtime-evidence bullet above), and on a device you can only reach over serial, an interleaving you can predict is an interleaving you can debug.

3. **Allocation budget on CircuitPython.** Per the runtime-evidence section above, every `await x` on CP allocates a fresh generator from the `__await__()` call. In a `recv_until` loop polling for bytes, that's one heap allocation per tick during receive — measurable churn under the per-tick allocation budget in AGENTS.md. `yield from x` has no such overhead; tokens are cacheable and reusable across yields.

4. **Smaller lint surface.** A `def` + `yield` substrate offers no asyncio-shaped syntactic affordance. A user who has never seen `async def` cannot reach for `import asyncio`. The asyncio ban (item 2 above) lints code that *can't be written in the legal syntax*, so it's defense-in-depth rather than load-bearing.

The cost is that post-PEP-492 Python authors expect `async`/`await` as the modern idiom. That cost is real but narrow: the chumicro user-facing surface is four helpers (`connect`, `send_all`, `recv_until`, `recv_exact`) plus the registration call. One worked example in the runner README is enough to bridge the idiom gap.

## Rejected

- **Adopt asyncio as the scheduler.** Inherits Adafruit asyncio issue #4 (broken stream layer on CP), unmaintained substrate, `Task`-object-per-service allocation cost, and reactor-vs-runner loop-ownership conflict.

- **`async def` + `await` syntax against the runner-driven scheduler.** Technically equivalent to generators-with-`yield from` at the substrate level on MP, but the four reasons in *Why generators, not async/await* above (yield-point hygiene, transparency, CP allocation cost, lint surface) all cut the same direction. The "modern idiom" win does not survive contact with the embedded constraints.

- **Make generator-driven sequential I/O the cross-cutting service model.** Decision 0051's reasoning still applies for reactive services — MQTT keepalive, button debounce, sensor polls read more naturally as `check`/`handle` than as `while True:` loops with `yield Sleep(N)`. Two service shapes is real conceptual overhead, but forcing sequential services into explicit state machines (or forcing reactive services into per-task allocations) is worse on both ends. Default to `check`/`handle`; reach for `add_generator` only when the work is naturally one-shot sequential I/O. Re-posed with post-realignment field data and closed 2026-07-04 (verdict KEEP, with explicit reopening criteria) — see [`plans/reviews/2026-07-04-check-handle-generators-repose.md`](../reviews/2026-07-04-check-handle-generators-repose.md): a two-repo census found 43 sister-repo check/handle registrations and zero app-code generator tasks, per-task RAM at parity, and the generator lane measured as a 278-line *client* of the check/handle contract rather than a peer.

- **Ship a `GeneratorService` base class as part of the public surface.** The user has to know they are writing a generator either way. The class form adds an inheritance entry point without expanding capability; a user who wants a state-bearing class wraps their own class around a generator they register. The internal `_GeneratorWrapper` that `add_generator()` constructs stays private.

- **Inject I/O primitives as a scheduler-as-DI abstraction.** Academically clean (library code calls `yield from self._io.recv_until(...)` against an injected `RunnerIO`) but adds per-call method-dispatch indirection in hot paths, requires maintaining parallel implementations per primitive, and inherits the broken substrate's bugs in any asyncio-backed implementation that would ship.

- **Ship an asyncio bridge.** Defer until a real user asks. The duck-typed `check`/`handle` contract is the escape hatch — asyncio users drive chumicro services from a polling adapter (~5 lines), losing the I/O-sleep optimization but functional.

## Consequences

- New `chumicro_runner` public API: `runner.add_generator(gen) -> GeneratorHandle`, `GeneratorHandle.done`, `GeneratorHandle.cancel()`. The wait objects a generator yields are **duck-typed, not named classes** — any object exposing `io_socket` / `io_wants_read` / `io_wants_write` / `next_deadline` works (an earlier `ReadReady` / `WriteReady` / `Sleep` token design with `ready()` / `result()` methods was dropped as needless ceremony; [Decision 0091](0091-event-wait-tokens-for-generator-tasks.md) later added the `ready(now_ms)` predicate alone, as a duck-typed attribute for event waits, keeping named classes and `result()` out). Internal `_GeneratorWrapper` stays private. Existing check/handle services and their registration paths are unchanged.

- A yielded wait exposes `io_socket` + `io_wants_read` / `io_wants_write` (poll interest) and an optional `next_deadline` (a timeout). They are **not** awaitables — no `__await__`. They are cacheable: an EAGAIN-loop helper constructs one wait outside the loop and re-yields it, so steady-state iterations allocate nothing.

- **Amended 2026-08-17 (`chumicro_runner` 0.22.0, `chumicro_timing` 0.9.0): a wait never compares times; the driver does, with its own clock.** Two things drove this. The wait protocol was reconciled only inside `_GeneratorWrapper.check()`, so `runner.add_generator` was effectively the only driver that could time a generator correctly, which taxed the adoption path Decision 0042 and the standalone-integration guide exist to keep open. And `_GeneratorWrapper` compared deadlines with a module-level `from chumicro_timing.ticks import ticks_diff` while `Runner` routed every other comparison through the injected `self._ticks`, so a caller who passed `ticks=` got their clock honoured everywhere except the generator gate. Reproduced with the non-wrapping clock the standalone-integration guide tells adopters to write: a four-day deadline aliases to "already elapsed" under the 2^29 modular compare and the task resumed on its first tick. The rule is now explicit: **a yielded wait publishes its condition and never judges a time itself.** `ready(now_ms)` answers only conditions needing no clock (`Signal.is_set`); `next_deadline(now_ms)` publishes a deadline for the driver to compare; `io_socket` / `io_interest` remain sleep hints. The gate is three ordered cases (honour `ready`, else resume once `next_deadline` lands, else resume on any pass), documented with a copy-paste implementation in the runner guide and the standalone-integration page. `_GeneratorWrapper` now takes the runner's `ticks_diff` at construction. An earlier draft of this amendment pushed the compare *into* the helpers (a self-guarding `sleep_until`, a deadline-aware `Signal.ready`); that was reverted because giving a helper its own clock is precisely what created the injection break, and it also grew the library past its flash ceiling. Removing the hardcoded import instead left `chumicro_runner` 10 B *smaller* than before the change, so no budget moved. Covered by `libraries/runner/tests/test_socket_generators.py` (`test_runner_gates_deadlines_with_the_clock_it_was_given`, plus the "without a runner" cases).

- Socket generator helpers live in `chumicro_sockets.generators`: `connect(connector)`, `send_all(sock, data)`, `recv_until(sock, sep, max_bytes=...)`, `recv_exact(sock, n)`. `connect` takes an already-built `SocketConnector` (from `tcp_client_connector` / `tls_client_connector`), drives it across ticks, and returns the connected socket via PEP 380 `return value`; callers wrap it in `try/finally` (or `with`). The scheduler-side `sleep_until` (a deadline wait) stays in `chumicro_runner.generators`. Existing synchronous and tick-driven-connector factories stay — these are an additional surface, not a replacement.

- CHU033 bans `async def` / `await` / `async with` / `async for` and `import asyncio` / `from asyncio import …` / `import uasyncio` in `libraries/`, `support/`, and `workbench/`, AST-based and excluding `functional_tests/`.

- `chumicro_runner` `VERSION` minor bump (new public surface). `chumicro_sockets` `VERSION` minor bump (new helpers). `workbench/checks` `VERSION` minor bump (new lint rule).

- Demo rewrite: `demos/sockets_runner_connector/app.py` collapses from ~80 lines to ~7. The current explicit-state-machine version moves to `demos/sockets_runner_connector_explicit/` as a teaching companion that shows the underlying machinery.

- Decisions 0051 and 0080 are edited in place to distinguish "the asyncio module / event loop" (rejected) from "the runner-driven generator substrate" (the path this ADR takes). The `async`/`await` keywords stay rejected alongside the module.

- Reactive libraries keep their `check`/`handle` cores. [Decision 0089](0089-generator-surfaces-on-networking-libraries.md) later adds generator *surfaces* to two of them — a one-shot `fetch` in `chumicro_requests` and a receive-stream `next_message` in `chumicro_websockets` — while MQTT, the HTTP server, and WiFi stay purely reactive; see it for the rule on which work earns a generator surface. Two service shapes coexist; library authors default to `check`/`handle` and reach for `add_generator` only when the work is naturally sequential await. The networking guides with a generator surface teach that surface first as of 2026-07-18 (a teaching-order call); the default shape and this contract are unchanged.

- Asyncio users who want to drive chumicro services from their own loop use the existing duck-typed `check`/`handle` contract via a polling adapter (~5 lines of glue per service). They lose the `Runner.wait()` `ipoll`-based I/O sleep optimization; this is documented, not fixed.
