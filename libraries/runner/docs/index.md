---
title: "chumicro-runner: run many jobs in one loop on CircuitPython and MicroPython"
---

# chumicro-runner

**Run several jobs from one `while True:` loop on a board, with no `time.sleep()` and no `async`.**

A `time.sleep()` blink works until the board needs a second job.  `chumicro-runner` keeps your `while True:` loop and puts a small scheduler inside it.  Each job is registered once, with how often it runs.  `runner.tick()` runs whichever jobs are due.  `runner.wait()` sleeps the board until the next one is.  Every ChuMicro network library registers with the same runner, so your LED keeps blinking through a slow HTTP response or a stalled server.  It runs on CircuitPython, MicroPython, and CPython.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_runner

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner

# CPython
pip install chumicro-runner
```

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Print one line every second and another every five seconds, from one loop:

```python
from chumicro_runner import Runner

def every_second(now_ms):
    print("one second")

def every_five_seconds(now_ms):
    print("five seconds")

runner = Runner()
runner.add_periodic(every_second, period_ms=1000)
runner.add_periodic(every_five_seconds, period_ms=5000)

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
```

This program runs as-is on a laptop and on a board.  Each job is a function that does one quick step and returns.  `runner.tick()` reads the clock once, runs every job that is due, and returns that reading in milliseconds as `now_ms`, the same value it passed to each job.  `runner.wait(now_ms)` sleeps until the next job is due.

Keep the `wait()` line.  Without it, the loop spins the CPU flat out and wastes power.

## Documentation

- [User Guide](guide.md): from a `time.sleep()` blink to the runner, then timed jobs, services, and generator tasks in order, how `wait()` sleeps, and what happens when a job raises
- [API Reference](api.md): `Runner` with its `add_periodic` / `add` / `add_generator` registrations, `TaskHandle`, `GeneratorHandle`, and the `sleep_until` pause helper
- [Testing Helpers](testing.md): `CallRecorder`, `validate_service`, and `FakePoller` for testing your own jobs on a laptop

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
