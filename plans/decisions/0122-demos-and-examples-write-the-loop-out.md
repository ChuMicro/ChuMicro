# Decision 0122: Demos and examples write the main loop out by hand

Status: `accepted`
Date: `2026-08-18`
Summary: Demos, library examples, and workbench-template projects spell their main loop as `while ...: runner.tick(); runner.wait(now_ms)`; `run_until` stays on `Runner` for application code.
Related: Decision [0102](0102-runner-run-until.md) (`run_until` is bounded, not the main loop), Decision [0080](0080-runner-reactor.md) (the loop's two beats), Decision [0014](0014-runner-pattern.md) (the runner contract).

## Context

Decision 0102 shipped `run_until` and named it the standard tail for demos, on the reasoning that a raw `while` in every demo duplicates the wait, timeout, and error semantics N times. That reasoning holds for production application code and is wrong for teaching code. The audience for `demos/` and `libraries/*/examples/` is an Adafruit-Learn beginner who is learning CircuitPython, MicroPython, and their tools at the same time as ChuMicro, and for whom `while True:` at the bottom of `code.py` is already the one loop they know. A file that ends in `runner.run_until(handle)` hands that reader a call they cannot see inside, in the exact place they expected the loop to be.

The drift went further than 0102 intended. `run_until()` with no arguments *is* an unbounded main loop, and the workbench template's own agent guidance told contributors to use it, warning them off `while True: runner.tick()` as a busy-spin. That warning is only true of a loop with no `wait()` in it; the correct hand-written loop calls `runner.wait(now_ms)` and parks the CPU exactly as `run_until` does. So the template's projects, its examples, and every networked demo ended up with no visible loop at all, contradicting both the root README and 0102's own "the application's own `while True:` stays hand-written and single-steppable."

## Decision

Teaching code writes the loop out. `demos/*/app.py`, `libraries/*/examples/*.py`, and the workbench template's `projects/` and `examples/` end with the loop on the page:

```python
while True:
    now_ms = runner.tick()   # every registered service takes one small step
    runner.wait(now_ms)      # then the CPU parks until the next event or deadline
```

- **`runner.wait(now_ms)` is what makes it correct, not `run_until`.** A `while True: runner.tick()` with no `wait()` is the busy-spin to reject. The two-line loop above parks the CPU on the same code path `run_until` uses, because `run_until` is that loop. Guidance that warns against hand-written loops must name the missing `wait()`, not the `while`.
- **Everything the program needs to notice is an `if` inside the loop, before the `wait()`.** A finished generator (`if handle.done: break`), an exhausted wifi reconnect policy, a demo deadline (`if give_up.expired(now_ms):`). Check completion *before* `wait()`: a finished task re-arms no deadline, so `wait()` would idle on a socket with no event coming.
- **Demos carry their deadline as a `chumicro_timing.Deadline`.** `Deadline(_DEMO_DEADLINE_MS, ticks_ms())` plus `give_up.expired(now_ms)` reads as English and is a primitive the reader will use again, where `timeout_ms=` was an argument to a call they could not open.
- **`run_until` stays.** It remains on `Runner`, documented in the runner README and guide as the one-call form of the loop, and is the right call in application code nobody is reading to learn from. Decision 0102's contract is unchanged; only its audience is narrowed.

## Rejected

- **Leaving demos on `run_until` and fixing the docs instead** — the docs already said the application owns its `while True:`. The demos were the thing a reader copies, so the demos were the thing to change.
- **A shared `demo_loop()` helper in the test harness** — removes the loop from the page again, one indirection further away, and the harness import in demo code is already a wart.
- **Converting only the run-forever cases** — leaves a beginner reading two different loop idioms across sibling demos, which is the confusion this decision removes.

## Consequences

- Nine demo `app.py` files, both `receive_stream.py` examples, and every workbench-template project and example now show the loop; `run_until` no longer appears in teaching code in either repo.
- The mqtt and websockets guides' "Getting started" snippets show the loop, matching the example files they point at. The runner guide shows the loop first and names `run_until` as its one-call form.
- The workbench template's `AGENTS.md` and `CONTRIBUTING.md` state the rule as "write the loop out; `wait()` is the line that matters" instead of banning `while True`.
- Demos are a few lines longer each, which is the cost being paid on purpose.
- New demos follow the shape recorded in `demos/README.md`, "Adding a demo".
