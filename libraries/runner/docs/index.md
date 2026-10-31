---
title: "chumicro-runner: run many jobs in one loop on CircuitPython and MicroPython"
---

# chumicro-runner

**Run several jobs from one `while True:` loop on a microcontroller, with no `time.sleep()` and no `async`.**

A `time.sleep()` blink works until the board needs a second job: while the loop sleeps for the LED, nothing else happens.  The runner keeps your `while True:` loop and puts a small scheduler inside it.  You register each job once and say how often it runs; `runner.tick()` runs whichever jobs are due, and `runner.wait()` sleeps the board until the next one is.  Every networked library in ChuMicro (`chumicro-wifi`, `chumicro-sockets`, `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`) registers with the same runner, so your LED keeps blinking through a slow HTTP response or a stalled MQTT peer.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_runner

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner

# CPython
pip install chumicro-runner
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

## Quick example

Two jobs at two different paces, from one loop:

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

This runs as-is on your computer and on a board.  `now_ms` is the time of the current tick in milliseconds; the runner passes it to every job.

## Documentation

- [User Guide](guide.md): from a `time.sleep()` blink to the runner, then timed jobs, services, and generator tasks in order, how `wait()` sleeps, and what happens when a job raises
- [API Reference](api.md): `Runner` with its `add_periodic` / `add` / `add_generator` registrations, `TaskHandle`, `GeneratorHandle`, and the `sleep_until` pause helper
- [Testing Helpers](testing.md): `CallRecorder`, `validate_service`, and `FakePoller` for testing your own jobs on your computer

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
