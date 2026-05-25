# Decision 0087: Async/await syntax without the asyncio module

Status: `accepted`
Date: `2026-05-25`
Summary: `async`/`await` permitted inside coroutines registered via `runner.add_coroutine()`; `import asyncio` forbidden — runner drives coroutines via `.send()` with our own wait-tokens.
Related: Decision 0014 (runner pattern), Decision 0051 (runner-shaped policy), Decision 0080 (runner reactor), Decision 0081 (non-blocking connect via tick-driven connector)

## Context

The runner-shaped contract from Decisions 0014 / 0051 (`check(now_ms) -> bool` + `handle(now_ms)`, plus the `io_socket` / `io_wants_read` / `io_wants_write` attributes added by 0080) reads cleanly for reactive services — MQTT keepalive, WiFi state changes, button debounce, sensor polls — but is verbose for sequential I/O state machines. The `demos/sockets_runner_connector/app.py` `EchoService` is the canonical case: ~80 lines of explicit state machine — four state strings, three `_handle_*` methods, manual `_send_offset` tracking, three `io_wants_*` properties — for what is conceptually "connect, send, recv, close." A first-time custom-protocol author bounces off the ceremony.

Decisions 0051 and 0080 both rejected adopting asyncio, but the rejection elided a load-bearing distinction. Reading MicroPython / CircuitPython sources clarifies it:

- `extmod/../py/objgenerator.c:51-87` shows coroutines and generators allocate the same `mp_obj_gen_instance_t` struct, differing only by type tag (`mp_type_gen_instance` vs `mp_type_coro_instance`). `mp_obj_gen_resume` at line 207 handles both identically.
- `py/compile.c:2790-2797` shows `await x` compiles to `x.__await__()` + `MP_BC_YIELD_FROM` — pure compiler-and-VM machinery, no module imports.
- `py/mpconfig.h:1335` (`MICROPY_PY_ASYNC_AWAIT`) and `py/mpconfig.h:1932` (`MICROPY_PY_ASYNCIO`) are independent firmware flags. The syntax is enabled at `CORE_FEATURES` (level 10); the asyncio module requires `EXTRA_FEATURES` (level 30).

So the syntax keywords (`async def`, `await`, `async with`, `async for`) are a language feature with zero dependency on the asyncio module. Driving a coroutine via `.send()` from a custom scheduler — the architectural posture `trio` and `curio` take on CPython — is mechanically supported on all three target runtimes today.

The `asyncio` module itself remains a poor substrate to depend on. Adafruit's CircuitPython port (the only path to asyncio on CP) has [issue #4](https://github.com/adafruit/Adafruit_CircuitPython_asyncio/issues/4) open since 2021-11-18: `asyncio/stream.py` imports `usocket`, a MicroPython-only module not present on CircuitPython, so `asyncio.open_connection` / `start_server` / `StreamReader` / `StreamWriter` are all broken on CP. Recent commits to the repo are upstream-sync, not bug-fix. Building on top of that library inherits a broken substrate.

## Decision

1. **Library code may use `async`/`await` syntax** to express sequential I/O state machines linearly. Coroutines are registered with the runner via `runner.add_coroutine(coro)`; the runner drives the coroutine via `.send()`, treating it as a check/handle-shaped service internally. The runner's external dispatch surface is unchanged.

2. **Library code must not import the `asyncio` module.** Enforced by a new CHU lint rule across `libraries/`, `support/`, and `workbench/`. Wait-tokens (`ReadReady`, `WriteReady`, `Sleep`, `Done`) live in `chumicro_runner`; each implements `__await__` to yield itself into the generator protocol the runner drives.

User-facing surface — one registration entry point:

```python
async def echo_run(host, port, radio):
    async with connect(host, port, radio) as sock:
        await send_all(sock, b"hello chumicro\n")
        reply = await recv_until(sock, b"\n")

handle = runner.add_coroutine(echo_run(host, port, wifi.adapter.radio))

while not handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

The returned `CoroutineHandle` exposes `.done`; check/handle/io_* are present for the runner's internal dispatch but are not part of the user-facing contract. Users who want a state-bearing class around the coroutine own that class shape themselves — they register `self._run()` from a `start()` method and expose whatever state they need on `self`.

The runner's while-loop contract is unchanged: `while not done: now_ms = runner.tick(); runner.wait(now_ms)`.

### Rejected

- **Adopt asyncio as the scheduler.** Inherits Adafruit asyncio issue #4 (broken stream layer on CP), unmaintained substrate, `Task`-object-per-service allocation cost, and reactor-vs-runner loop-ownership conflict. The asyncio module remains forbidden by the lint rule.

- **Make async/await the cross-cutting service model.** Decision 0051's reasoning still applies for reactive services — MQTT keepalive, button debounce, sensor polls read more naturally as `check`/`handle` than as `async def while True:` loops with `await sleep(N)`. Two service shapes is real conceptual overhead, but the alternative — forcing sequential services into explicit state machines, or forcing reactive services into per-coroutine allocations — is worse on both ends.

- **Use `def` + `yield from` instead of `async def` + `await`.** Byte-identical at the VM level (the `__await__` lookup adds one method dispatch per await, otherwise the same `YIELD_FROM` opcode). `async`/`await` is the post-PEP-492 idiom any Python author recognizes; the only reason to refuse it would be to dodge the asyncio module, and the independent-config-flag evidence makes that dodge unnecessary.

- **Ship a `CoroutineService` base class as part of the public surface.** The user has to know they are writing a coroutine either way — either by inheriting from `CoroutineService` and writing `async def run()`, or by passing an `async def` to `add_coroutine()`. The class form adds an inheritance entry point without expanding capability; a user who wants a state-bearing class wraps their own class around a coroutine they register, which is the same number of moving parts with less surface area to maintain. The internal `_CoroutineWrapper` that `add_coroutine()` constructs stays private.

- **Inject I/O primitives as a scheduler-as-DI abstraction.** Academically clean (library code calls `await self._io.recv_until(...)` against an injected `RunnerIO` / `AsyncioIO`) but adds per-call method-dispatch indirection in hot paths, requires maintaining parallel implementations per primitive, and inherits the broken substrate's bugs in any asyncio-backed implementation that would ship.

- **Ship an asyncio bridge.** Defer until a real user asks. The duck-typed `check`/`handle` contract is the escape hatch — asyncio users drive chumicro services from a polling adapter (~5 lines), losing the I/O-sleep optimization but functional. A bridge that papered over the scheduler incompatibility would require touching asyncio's private internals and inherit Adafruit asyncio's bugs.

## Consequences

- New `chumicro_runner` public API: `runner.add_coroutine(coro) -> CoroutineHandle`, `CoroutineHandle.done`, wait-token classes (`ReadReady`, `WriteReady`, `Sleep`, `Done` sentinel). Internal `_CoroutineWrapper` stays private. Existing check/handle services and their registration paths are unchanged.

- Wait-tokens implement `__await__` (yield self), `ready(now_ms) -> bool`, and `result(now_ms)` (the value `.send()`-ed back into the coroutine). Steady-state allocation budget unchanged from current ([Decision 0051](0051-runner-shaped-as-project-policy.md) tracemalloc standard) — one short-lived token per `await` boundary, comparable to today's explicit state-machine attribute writes.

- New socket coroutine helpers in `chumicro_sockets`: `connect(host, port, radio)`, `send_all(sock, data)`, `recv_until(sock, sep, max_bytes=...)`, `recv_exact(sock, n)`. `async with connect(...) as sock:` supported via `__aenter__` / `__aexit__`. Existing synchronous and tick-driven-connector factories stay — these are an additional surface, not a replacement.

- New CHU lint rule bans `import asyncio` / `from asyncio import …` / `import uasyncio` in `libraries/`, `support/`, and `workbench/`. Deploy bundle staging refuses to copy any module named `asyncio*` to a device.

- `chumicro_runner` `VERSION` minor bump (new public surface). `chumicro_sockets` `VERSION` minor bump (new helpers). `workbench/checks` `VERSION` minor bump (new lint rule).

- Demo rewrite: `demos/sockets_runner_connector/app.py` collapses from ~80 lines to ~10. The current explicit-state-machine version moves to `demos/sockets_runner_connector_explicit/` as a teaching companion that shows the underlying machinery.

- Decisions 0051 and 0080 are edited in place to distinguish "the asyncio module / event loop" (still rejected) from "the `async`/`await` syntax keywords" (allowed inside coroutines driven by the runner).

- Reactive libraries (MQTT, WiFi, HTTP server, websockets) keep their `check`/`handle` shape unchanged. They may optionally adopt `add_coroutine`-style internals for genuinely sequential subpaths in future, but no migration is mandated. Two service shapes coexist; library authors pick based on whether the work is naturally sequential or naturally reactive.

- Asyncio users who want to drive chumicro services from their own loop use the existing duck-typed `check`/`handle` contract via a polling adapter (~5 lines of glue per service). They lose the `Runner.wait()` `ipoll`-based I/O sleep optimization; this is documented, not fixed.
