# Cooperative multitasking with generators

If you know ordinary Python functions, loops, exceptions, and I/O, you can run this example without an earlier ChuMicro tutorial. Two jobs print three `fast` lines and three `slow` lines, then finish and return you to the laptop prompt.

The application owns the outer `while True` loop. Each `tick()` captures the time, checks registered work, and executes eligible handlers sequentially, returning the captured time as `now_ms`. A generator suspends at a yield while preserving its local progress. Its yielded object describes a wait. A bare `yield` asks to resume on the next tick.

`add_generator` takes a fresh generator object and immediately advances it to its first yield. Later, the runner resumes it with `.send(now_ms)`. Here, `sleep_until` waits for an absolute tick deadline constructed with wrap-safe `ticks_add`.

## Run two jobs

On your laptop, use an active Python environment with `chumicro-runner` and `chumicro-timing` installed, following the CPython host-test route in [installation](install.md). The example needs no board peripherals, network, account, or credentials.

Save this complete listing as `generator_jobs.py`:

```python
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_ms


def report(label, interval_ms):
    for count in range(3):
        print(label, count + 1)
        yield from sleep_until(ticks_add(ticks_ms(), interval_ms))


runner = Runner()
fast = runner.add_generator(report("fast", 100))
slow = runner.add_generator(report("slow", 250))

try:
    while True:
        now_ms = runner.tick()
        if fast.error is not None:
            raise fast.error
        if slow.error is not None:
            raise slow.error
        if fast.done and slow.done:
            break
        runner.wait(now_ms)
finally:
    fast.cancel()
    slow.cancel()
```

In your laptop terminal, from that file’s directory and with the same environment active, run:

```bash
python generator_jobs.py
```

Registration prints `fast 1` and `slow 1` before the loop starts. Later progress is interleaved, with timing dependent on the execution environment. Expect six printed lines in total, followed by the laptop prompt. This host test makes no board writes. The same application can run on MicroPython or CircuitPython after normal library installation.

The return value of `add_generator` is a **task handle**. Here, `fast` and `slow` expose `error` for task-body failure and `done` for return, failure, or cancellation. The loop inspects errors before completion, so failure is not mistaken for successful completion. Both checks happen before `wait(now_ms)`.

## Helpers and wait conditions

`yield from` delegates to a helper generator and gives the helper’s return value back to its caller. Delegation hands control to the scheduler only when something actually yields. Calculations and I/O between yields are synchronous. A long calculation or blocking I/O delays the other jobs, so keep each turn’s work short and bounded.

A wait’s `ready(now_ms)` expresses its readiness condition. Its `next_deadline(now_ms)` supplies an absolute tick deadline. A socket plus an interest specifies which socket events can wake the poller. Socket work can retry on later ticks. If a retry encounters EAGAIN, meaning the operation would block, it returns to suspension.

`wait` uses socket readiness and the next deadline to decide when to wake. It returns immediately when nothing is waitable or a deadline is already due. With a socket and no deadline, it may wait indefinitely. This is why the application checks completion and errors before idling.

Generators are adapted onto the same service dispatch as other runner work. Reactive services use `check` to decide whether work is ready and `handle` to perform it. Generators suit sequential flows and receive loops. See the [full service contract](https://chumicro.com/ChuMicro/runner/stable/guide/#the-service-contract) for the protocol.

## Cleanup and debugging

Put resource-release code in a task generator’s own `finally` block. `cancel()` closes the task, allowing that cleanup to run. The caller’s `finally` ensures both handles are cancelled on exit, whether after completion or an exception. Cleanup is synchronous, not another scheduled phase.

Explicit task-error inspection makes failure handling visible in the application. For debugging, the runner also offers an optional error callback and fault counters.

For repeatable host checks, supply the runner with a fake clock and, optionally, a fake poller. Keep `ticks_ms`, `ticks_add`, and `ticks_diff` consistent and wrap-safe across the supplied clock and your waits. Use the [runner testing helpers](https://chumicro.com/ChuMicro/runner/stable/testing/) for these checks, then follow [device testing](contributing/device-testing.md) on physical boards to check device behavior.

## Choosing this model

On CPython, [Python 3.14 asyncio](https://docs.python.org/3.14/library/asyncio-task.html#task-object) is also cooperative and provides task exception and stack inspection. ChuMicro’s distinguishing choices here are generator syntax, an explicit tick/wait loop, and service and wait contracts. That comparison concerns CPython, not a guarantee about MicroPython or CircuitPython. Memory and debugging comparisons need their own runtime-specific measurements.

Budget for task handles, generator frames, wait objects, and buffers. Helpers have their own allocation costs. Reusable waits can avoid recreating a wait during retries, but there is no universal zero-allocation guarantee.

## Next tasks

For your own transport and clock, use [standalone integration](contributing/standalone-integration.md). For deployment file selection, use [slimming your deploy](contributing/slimming-your-deploy.md).

For measurement interpretation, baseline scope, and flash budgeting, start with [quality and resource costs](quality-and-resource-costs.md) before consulting the [recorded benchmark baseline](https://github.com/ChuMicro/ChuMicro/blob/main/scripts/benches/baseline.toml) or [library size budgets](https://github.com/ChuMicro/ChuMicro/blob/main/size-budgets.toml).

To turn reusable work into a library, follow [adding a library](contributing/new-library.md).
