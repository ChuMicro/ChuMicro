---
paths:
  - "libraries/**/*.py"
  - "support/**/src/**/*.py"
  - "demos/**/*.py"
---

# Library code

Applies to `libraries/` and `support/<name>/src/`, cross-runtime by default. Not to `workbench/` or `scripts/`.

## Reactor budget

- ≤5 ms per `tick()` / `handle()` call. Only `Runner.wait` blocks ([Decision 0080](../../plans/decisions/0080-runner-reactor.md)).
- No `async` / `await` / `asyncio` / `uasyncio` ([Decision 0087](../../plans/decisions/0087-generators-for-sequential-io.md), `CHU033`).
- No ISR carrying application control flow. A device library may own a capture interrupt when the handler allocates nothing, captures raw edges only, runs no user callback in interrupt context, and bounds and counts its overflow ([Decision 0124](../../plans/decisions/0124-buttons-and-knobs-libraries.md)).
- No blocking TCP/TLS handshake. Use `chumicro_sockets`'s tick-driven connector ([Decision 0081](../../plans/decisions/0081-non-blocking-connect-via-tick-driven-connector.md)).
- Offenders: `time.sleep(>0.005)`, `select.poll(>0)`, blocking `getaddrinfo`, `socket.recv()`, `machine.lightsleep`, MicroPython `os.urandom`.

## Time

- Route all time math through `chumicro_timing` (`ticks_ms`, `ticks_diff`, `ticks_add`, `Heartbeat`). Never call `time.monotonic`, `time.ticks_ms`, or `supervisor.ticks_ms` directly. Mixing a tick deadline with a wall clock reads as a stalled service.
- A class taking `ticks=` compares every deadline through that clock (`self._ticks.ticks_diff(...)`), never through a module-level `ticks_diff` import in a helper. `FakeTicks` agrees with the hardcoded call and misses the swap, so test with a clock that disagrees.
- A suspended object publishes its deadline through `next_deadline(now_ms)` and judges no time itself, which leaves `ready(now_ms)` for conditions needing no clock. Reproduction and the disagreeing clock: [`plans/patterns.md`](../../plans/patterns.md) "Injected clocks".

## Memory

- Steady-state zero allocation per tick: allocation delta over 1000 ticks ≤64 bytes inside `tick()` / `handle()` / `check()` / any parser inner loop. Verify with `gc.mem_alloc()` bracketed by `gc.disable()`.
- Named hot-path offenders and their rewrites:
  - f-strings and `.format()` each allocate a new `str`. Use `log.info("...%d...", n)` with logger-side interpolation, or guard with `if log.is_enabled(INFO):`.
  - dict / list / tuple / set literals inside the loop. Reuse a module-level constant or a cleared scratch container.
  - `bytes(view[a:b])` to feed `struct.unpack`. Use `struct.unpack_from(fmt, buf, offset)`.
  - `bytes(view).decode("utf-8")`. Use `str(view, "utf-8")`; the 3-arg constructor takes buffer-protocol objects and skips the intermediate `bytes` copy.
  - `int.from_bytes(bytes(buffer[a:b]), ...)`. Drop the `bytes()` wrapper; `int.from_bytes` accepts any buffer-protocol object.
  - `enumerate` / `zip` / `reversed` in a hot loop each allocate an iterator. Index by hand or restructure.
  - `self.x.y.z.method()` chains used twice or more. Cache to a local before the loop.

  F-strings outside hot paths are fine. More recipes: [`plans/patterns.md`](../../plans/patterns.md) covers buffer reuse, the `list.clear()` and method-`getattr` allocators, and `gc.mem_alloc` churn tests.
- `gc.collect()` is forbidden in hot paths, required at the end of an `__init__.py` with substantial import-time state, and recommended before returning from a method that handled a large blob ([Decision 0084](../../plans/decisions/0084-gc-collect-policy.md)).
- `import gc` at module top and reuse it. No alias-and-`del` dance.
- Bound any `bytearray(N)` / `bytes(N)` whose `N` comes from a peer-controlled field at a documented cap knob (`max_message_bytes`, `max_body_bytes`, `max_frame_bytes`) and refuse above it, or use a pre-allocated buffer as a rolling sink. A comment claiming heap-safety is not a bound.

## Shape

- Constructor-inject time, I/O, and network dependencies. Fakes go in the library's `testing.py`.
- Declare substrate (`chumicro-sockets`, `chumicro-timing`) in `pyproject.toml` but keep `src/<name>/` free of top-level `import chumicro_<substrate>`, which keeps it off the deploy bundle. Duplicate a trivial helper rather than reaching for a sibling library.
- Absolute imports only; relative imports break CircuitPython RAM-mode deploys (ruff TID252).
- PEP 604 / 585 syntax (`int | None`, `list[int]`). Never import `typing`, never `from __future__ import annotations`.
- Mark runtime-specific files `__chumicro_runtimes__ = ("circuitpython",)`. Mark `testing.py` fakes `__chumicro_test_support__ = True` with no runtime marker.
- f-strings for formatting. `const()`, `memoryview`, and pre-allocated buffers here only.
- No `__slots__`; neither device runtime implements it.
- No pure-passthrough `@property`. Properties that compute or transform stay.
- Descriptive names, no single letters except `_`, abbreviations expanded (`environment`, `buffer`, `source`, `command`, `message`, `error`, `reference`, `address`, `exception`, `execute`). `CHU001` enforces it. Suppress only to match an upstream API.
- Prefer pure-Python implementations that run on all three runtimes.

## Examples and demos

- Examples import the public package only. No `if __name__ == "__main__":` guard. Hardware examples are prefixed `circuitpython_*.py` / `micropython_*.py`. Gated by `python scripts/run.py verify-examples`.
- A demo's `app.py` imports only what it demonstrates, prints its own `NAME key=value` lines, and lingers a few seconds before exiting ([Decision 0123](../../plans/decisions/0123-demos-read-like-a-first-project.md)). No `chumicro_test_harness` import in board-side demo code.
- Demos and examples write the main loop out: `while ...:`, then `runner.tick()`, then `runner.wait(now_ms)` ([Decision 0122](../../plans/decisions/0122-demos-and-examples-write-the-loop-out.md)). `run_until` hides the loop from the reader they exist to teach.
- Never deploy a `code.py` / `main.py` containing `microcontroller.reset()` or `machine.reset()`.

## Before calling it done

Changes touching I/O, hot paths, or runtime-specific behavior need a real board. Deploy to the tier the library targets (Pico W at minimum), run a one-minute REPL tail under load, and confirm no traceback, safe-mode banner, or silent stall. `chumicro-workspace deploy-example`, `chumicro-workspace deploy <project> --tail <seconds>`, or `chumicro-workspace repl --tail <seconds>`.
