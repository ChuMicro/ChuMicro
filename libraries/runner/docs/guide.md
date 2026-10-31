# User Guide

## Overview

`chumicro-runner` lets one `while True:` loop do several jobs, each at its own pace, without `time.sleep()`.  You register each job with a `Runner` once.  Inside the loop, `runner.tick()` runs whichever jobs are due and `runner.wait()` sleeps the board until the next one is.  Every networked ChuMicro library is a job you register the same way, so WiFi, MQTT, and your LED share one loop, and a slow server holds up nothing but its own job.

A few words this guide uses:

- **Job**: anything registered with the runner.  There are three kinds, covered in order of difficulty below: timed jobs, services, and generator tasks.
- **Tick**: one call to `runner.tick()`.  It reads the clock once and runs every job that is due.
- **`now_ms`**: that clock reading, in milliseconds.  `tick()` passes it to every job it runs and returns it, so everything in one tick agrees on the time.
- **Period**: how often a job runs, given as `period_ms`.

## Getting started

Here is the first program most board tutorials teach, with a button check added (CircuitPython shown):

```python
import time

import board
import digitalio

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
button = digitalio.DigitalInOut(board.BUTTON)   # or the pin your button is wired to
button.pull = digitalio.Pull.UP                 # reads False while the button is held

while True:
    led.value = not led.value
    time.sleep(0.5)
    if not button.value:
        print("pressed")
```

It looks fine until you press the button.  The board spends nearly all its time inside `time.sleep(0.5)` and looks at the button for an instant twice a second, so a quick tap that starts and ends during the sleep never reaches the program.  Shortening the sleep speeds up the blink too.  Each new job brings another sleep, and every sleep holds up every other job.

The runner keeps the `while True:` and takes the sleeps out of the jobs:

```python
import board
import digitalio
from chumicro_runner import Runner

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
button = digitalio.DigitalInOut(board.BUTTON)
button.pull = digitalio.Pull.UP
was_pressed = False

def blink(now_ms):
    led.value = not led.value

def watch_button(now_ms):
    global was_pressed
    pressed = not button.value
    if pressed and not was_pressed:   # print once per press, not once per read
        print("pressed")
    was_pressed = pressed

runner = Runner()
runner.add_periodic(blink, period_ms=500)         # every half second
runner.add_periodic(watch_button, period_ms=20)   # fifty times a second

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
```

Each job is a function that does one quick step and returns, so no job holds up another.  `tick()` calls `blink` every 500 ms and `watch_button` every 20 ms, and between those moments `wait()` sleeps the board.  The button gets read every 20 ms whatever the LED is doing.

`wait()` is the line that matters.  A loop that calls `tick()` with no `wait()` never sleeps: it spins the CPU flat out to find nothing due, and on battery that spinning is where the power goes.  With `wait()`, the loop goes round only when a job is due.

The [`circuitpython_button_led.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/circuitpython_button_led.py) and [`micropython_button_led.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/micropython_button_led.py) examples are complete versions of this program, and [`periodic_blink.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/periodic_blink.py) runs the blink half on your computer.

## Timed jobs

`runner.add_periodic(function, period_ms=...)` calls a function every `period_ms` milliseconds.  The function takes one argument, `now_ms`, and should return quickly; anything slow holds up every other job in the same tick.

```python
def log_status(now_ms):
    print("still running")

runner.add_periodic(log_status, period_ms=10_000)   # every 10 s
```

The first run comes one period after you register the job.  Two options change that:

```python
# Wait 2 s, then run every 5 s.
runner.add_periodic(read_sensor, period_ms=5000, start_after_ms=2000)

# Run 3 times, 1 s apart, then remove the job.
runner.add_periodic(calibrate, period_ms=1000, run_count=3)
```

### Changing a job while it runs

`add_periodic` returns a `TaskHandle`.  Keep it, and you can change the job later from anywhere, including from inside another job:

```python
log_job = runner.add_periodic(log_status, period_ms=10_000)

log_job.set_period(1000)    # log every second instead
log_job.remove()            # stop logging altogether
```

Inside a job, pass the tick's time as well, `log_job.set_period(1000, now_ms)`, so the new period counts from this tick.  `log_job.period_ms`, `log_job.run_count`, and `log_job.active` report the job's current period, the runs it has left (`None` for unlimited), and whether it is still registered.  Change the period with `set_period()`; assigning `period_ms` directly leaves the next run at its old time.  [`runtime_control.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/runtime_control.py) uses all three: a faster period, a removed job, and a job with `run_count=1`.

### Keeping a steady rhythm

By default, the runner schedules a job's next run one period after the tick that ran it.  Runs never come closer together than `period_ms`, but any lateness carries forward: when a slow job holds every tick up by 80 ms, a 1 s job settles near one run every 1.08 s.

Pass `preserve_phase=True` when the long-run rate matters more than the gap, as for sampling, metering, or telemetry.  The next run then stays on the original schedule, and after a stall longer than one period the runner skips the missed runs instead of firing them all at once.

```python
runner.add_periodic(sample_adc, period_ms=100, preserve_phase=True)   # holds 10 per second
```

A late run catches back up to the schedule, so two runs can land closer together than `period_ms`.  Keep the default for anything that needs a minimum gap, such as a debounce or a rate limit.

### Jobs with no period

`runner.add(handler=function)` registers a function with no period.  It runs on every tick, which means every pass of the loop.  `wait()` only wakes the loop when a timed job is due or a socket is ready, so a job with no period runs exactly as often as something else wakes the loop.  If nothing else is registered, `wait()` has nothing to wait for and returns at once, and the loop spins.

[`basic_handler.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/basic_handler.py) counts its passes this way and shows the loop going round about once a second.  Anything that reads hardware, like a button or a sensor, needs its own `period_ms` so it runs on time.

## Services

A timed job runs on a schedule.  A service decides for itself whether there is work: it is an object with two methods the runner calls for you.

- `check(now_ms)` looks at the world and returns `True` when there is something to do.
- `handle(now_ms)` does it.  The runner calls it only on the ticks where `check()` returned `True`.

```python
class TemperatureAlarm:
    """Print a warning whenever the temperature is above limit_c."""

    def __init__(self, sensor, limit_c):
        self.sensor = sensor
        self.limit_c = limit_c
        self.reading = 0.0

    def check(self, now_ms):
        self.reading = self.sensor.temperature
        return self.reading > self.limit_c

    def handle(self, now_ms):
        print("too hot:", self.reading)


runner.add(TemperatureAlarm(sensor, limit_c=30), period_ms=5000)   # check every 5 s
```

`runner.add(service, period_ms=...)` calls `check()` once per period.  Without a period it calls `check()` on every tick, with the same caveat as [jobs with no period](#jobs-with-no-period).  `add` also takes `start_after_ms`, `run_count` (counting runs of `handle()`), and `preserve_phase`, and returns a `TaskHandle`.

Every network library in ChuMicro is a service, which is why `runner.add(wifi)` or `runner.add(mqtt_client)` is all the wiring they need.  They add a few optional members so `wait()` can watch their sockets; [Network services](#network-services) covers those.

### Order within a tick

Each tick runs in two passes.  First the runner works through the jobs in the order you registered them, skipping any whose period has not come round and calling `check()` on each service that is due.  Then it runs every job that is due, plus the `handle()` of each service whose `check()` said yes, in the same order.  No `handle()` runs until every `check()` has, so every service decides on the same state of the world.

```
tick():
  1. Read the clock once: now_ms
  2. For each job, in registration order:
     - skip it if its period has not come round
     - skip it if it is a service and check(now_ms) returns False
     - otherwise queue it
  3. Run every queued job with now_ms
```

## Generator tasks

Some work is a sequence of steps with waits between them: blink on, wait, blink off, wait; or connect, send, wait for the reply.  Written as a service, a sequence turns into a state variable and a chain of `if`s.  A generator task lets you write the steps top to bottom instead, like a `time.sleep()` program:

```python
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_ms


def pause(duration_ms):
    yield from sleep_until(ticks_add(ticks_ms(), duration_ms))


def heartbeat_blink():
    while True:
        led.value = True
        yield from pause(200)
        led.value = False
        yield from pause(200)
        led.value = True
        yield from pause(200)
        led.value = False
        yield from pause(1400)


runner.add_generator(heartbeat_blink())
```

A function with `yield` in it is a generator: calling `heartbeat_blink()` runs none of its body, it builds an object the runner can step through.  Each `yield from pause(...)` hands the loop back to the runner, which runs the other jobs and resumes the task on the next line when the pause is over.  `yield from pause(200)` is this task's `time.sleep(0.2)`, and nothing else stops while it waits.

`sleep_until(until_ms)` takes an absolute time on the `chumicro_timing` clock, which is why `pause()` adds the duration to `ticks_ms()`.  A bare `yield` gives the other jobs a turn and resumes on the next pass of the loop, whenever something else wakes it.

`add_generator` runs the task up to its first pause straight away, before it returns, so an exception raised before that pause comes out of `add_generator` itself.  [`generator_basic.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/generator_basic.py) runs this pattern beside a timed job.

### Task handles

`add_generator` returns a `GeneratorHandle`:

- `handle.done` turns `True` once the function returns, raises, or is cancelled.
- `handle.error` holds the exception it raised, or `None`.
- `handle.cancel()` stops it early.  Python raises `GeneratorExit` at the paused line, so any `finally` block in the function runs its cleanup.

An exception that escapes the function ends that task but not the loop; the runner counts it like any other job's exception ([When a job raises](#when-a-job-raises)).

Some tasks run once and finish, such as fetching settings at startup before the rest of the program begins.  Check `handle.done` right after `tick()`, before `wait()`: once the task has finished nothing re-arms a wake-up for it, so `wait()` would sleep until some other job is due.

```python
handle = runner.add_generator(fetch_settings())

while True:                        # first: until fetch_settings() returns
    now_ms = runner.tick()
    if handle.done:
        break
    runner.wait(now_ms)

if handle.error is not None:
    print("could not fetch settings:", handle.error)

while True:                        # then: the main loop, forever
    now_ms = runner.tick()
    runner.wait(now_ms)
```

`runner.run_until(handle)` is the one-call form of that first loop.  It ticks and waits until the task finishes and re-raises `handle.error` if the task died, so the failure is loud.  It also accepts a zero-argument function, returning once the function returns something truthy, and `timeout_ms=`, returning `False` if time runs out first.  `run_until(timeout_ms=500)` with no condition just runs the loop for that long.  The timeout is checked each time the loop wakes, so it lands late when nothing is due near it.  Use `run_until` in application code; the examples write the loop out so you can see it.

### Network I/O in a generator task

`chumicro_sockets.generators` provides pauses for socket work: `connect` opens a connection, `send_all` waits for room to send, and `recv_until` waits for the reply.  While `send_all` and `recv_until` wait on the network, the rest of the board keeps running:

```python
from chumicro_sockets import connector
from chumicro_sockets.generators import connect, recv_until, send_all


def echo_forever(host, port, radio):
    while True:
        try:
            sock = yield from connect(connector(host, port, radio=radio))
            try:
                yield from send_all(sock, b"hello\n")
                reply = yield from recv_until(sock, b"\n", max_bytes=4096)
                print("got", reply)
            finally:
                sock.close()
        except OSError as error:
            print("echo failed, trying again in 5 s:", error)
        yield from pause(5000)


runner.add_generator(echo_forever("echo.example", 7, radio=wifi.adapter.radio))
```

A failed step raises `OSError` at the line that failed, so a plain `try` / `except` handles a dropped connection, and the task tries again five seconds later.  `max_bytes` caps how much `recv_until` will buffer, so a peer that never sends the separator cannot fill the board's memory.

### Waiting for a callback

Some services report events through a callback, such as WiFi's `on_state_change`.  `Signal` and `wait_for` from `chumicro_timing.waits` let a generator task pause until that callback fires:

```python
from chumicro_timing.waits import Signal, wait_for

link_up = Signal()
wifi.on_state_change(lambda old, new: link_up.set(new))


def main_task(wifi):
    yield from wait_for(link_up)          # pause until wifi's callback calls link_up.set()
    sock = yield from connect(connector(HOST, PORT, radio=wifi.adapter.radio))
    ...
```

`wait_for` returns the value passed to `set()`.  The task resumes on the next pass of the loop after `set()` runs.  `wait_for(signal, deadline_ms=...)` bounds the wait: past that absolute tick it raises `OSError(ETIMEDOUT)` inside the task.  Call `signal.clear()` before waiting on the same signal again.  Use a signal for a one-time event the sequence has to wait for; an event the program reacts to every time it happens fits a service or a plain callback better.

### Choosing between a service and a generator task

| Use a service (`runner.add`) when... | Use a generator task (`runner.add_generator`) when... |
|---|---|
| The work is a reaction: a condition comes true and you respond | The work is a sequence: connect, send, receive, close |
| The state fits in a flag or two | The state would be a long chain of steps |
| You want `set_period()` and `run_count` to control it | You want the steps to read top to bottom |

Start with a timed job or a service.  Reach for a generator task when you catch yourself writing a state machine.  The two shapes mix freely in one runner.

### Why generators and not `async` / `await`?

The runner steps plain generators, and no ChuMicro library uses `async` / `await` or `asyncio`.  Four reasons, most important first:

1. **Every pause is real.**  `yield from` needs a generator, so ordinary helpers stay ordinary functions and every `yield from` you write is a place where the other jobs run.  With `async`, it is easy to mark a helper `async def` and `await` it when it never pauses, and the code looks as if it shares time when it does not.
2. **You can see and stop at every pause.**  A `yield` hands control to the runner in one step you can set a breakpoint on, and a traceback names the line a task was paused at.
3. **Less garbage on CircuitPython.**  CircuitPython compiles each `await` into a method call that builds a new object every time the line runs.  `yield from` compiles to one bytecode on both device runtimes.
4. **One less thing to mix up.**  Code written with generators has no event loop of its own to start, so it cannot end up fighting the runner for the `while True:`.

## Using `now_ms` in your own loop

`tick()` returns `now_ms`, so code in the loop body can use the same time the jobs saw:

```python
from chumicro_timing import Rate, ticks_ms

status = Rate(5000, ticks_ms())

while True:
    now_ms = runner.tick()
    if status.due(now_ms):
        print("still running")
    runner.wait(now_ms)
```

`wait()` only knows about jobs registered with the runner.  It can sleep straight past the `Rate`, and the `if` then runs late, by up to the longest gap between registered jobs.  Work that has to run on time belongs in `add_periodic`, where `wait()` can see it.

## How `wait()` decides how long to sleep

`runner.wait(now_ms)` is the only call in the loop that blocks.  Each call does three things:

1. **Updates the list of sockets to watch.**  Each network service reports which socket it is waiting on and whether it wants to read or write.  When nothing has changed, this step touches nothing.
2. **Works out how long it may sleep**: until the earliest job is due, or the earliest `next_deadline(now_ms)` a service reports, whichever comes first.
3. **Sleeps.**  With sockets to watch, it sleeps in `select.poll().ipoll()` and wakes early when one is ready, or waits for a socket alone when no job has a time.  With no sockets, it sleeps with `time.sleep_ms()`.  It returns at once when a job is already due, or when there is neither a socket nor a job with a time to wait for.

A ready socket only wakes the loop.  The next `tick()` still asks each service's `check()` whether to run `handle()`.  A socket that reports an error is also passed to its service's `io_error(now_ms, eventmask)`: that means `POLLERR`, or `POLLHUP` with nothing left to read.  A hang-up that arrives with `POLLIN` is a peer that sent its last bytes and closed, so the service reads them, and then the end of the stream, on its next turn.

The timing guide's [Choosing a wait](https://chumicro.com/ChuMicro/timing/stable/guide/#choosing-a-wait) table maps each kind of waiting to the helper that does it, across `chumicro_timing`, `chumicro_sockets`, and the runner.

### Network services

A service that owns a socket adds optional members so `wait()` can sleep until that socket is ready.  A service without them still works; `wait()` just never wakes early for it.

| Member | What it returns | Purpose |
|---|---|---|
| `io_socket` | a socket, or `None` | The socket whose readiness should wake the loop.  An object that keeps the real socket on `.sock` works too; the runner looks there |
| `io_interest(now_ms)` | `int` | `IO_READ` to wake when the socket has data, `IO_WRITE` to wake when it can send, both OR-ed together, or `0` for neither.  Import the bits from `chumicro_runner` |
| `next_deadline(now_ms)` | `int` or `None` | The tick by which the service must run even if no data arrives, such as a timeout or a keepalive |
| `io_error(now_ms, eventmask)` | nothing | Called when the socket reports `POLLERR`, or `POLLHUP` without `POLLIN` |

The runner reads these on every `wait()`, so a service can switch between reading and writing, or set `io_socket = None`, between ticks and the watch list follows on the next call.

```python
from chumicro_runner import IO_READ, IO_WRITE


class EchoClient:
    """Read bytes from a connected socket and send them back."""

    def __init__(self, sock):
        self.io_socket = sock
        self.wanted = IO_READ

    def io_interest(self, now_ms):
        return self.wanted

    def check(self, now_ms):
        return self.wanted != 0

    def handle(self, now_ms):
        # Read what is ready, then set self.wanted = IO_WRITE while
        # there are bytes waiting to go back out.
        ...

    def io_error(self, now_ms, eventmask):
        self.io_socket = None   # stop watching it from the next wait()
```

Every networked library in ChuMicro (`wifi`, `sockets`, `requests`, `http_server`, `mqtt`, `websockets`) implements these members, which is why each of them can sit idle without holding up your loop.

### The service contract

Here is everything the runner reads from an object you pass to `runner.add(service)`:

| Member | Required | When the runner reads it | For |
|---|---|---|---|
| `check(now_ms) -> bool` | yes | each `tick`, once the period has come round | deciding whether `handle` runs this tick |
| `handle(now_ms)` | yes | each `tick` where `check` returned `True` | one step of work |
| `io_socket` | no | each `wait` | the socket to watch, or `None` |
| `io_interest(now_ms) -> int` | no | each `wait` | `IO_READ` / `IO_WRITE` interest in `io_socket` |
| `next_deadline(now_ms) -> int \| None` | no | each `wait` | the latest time the service must run, data or not |
| `io_error(now_ms, eventmask)` | no | on `wait`, when `io_socket` reports `POLLERR`, or `POLLHUP` without `POLLIN` | moving to a failure state |

Three rules hold the set together.  `check` and `handle` are both required, and `runner.add` fails at once without them.  `io_socket` and `io_interest` come as a pair, since the runner reaches the socket through `io_interest`.  `io_error` needs an `io_socket` to report on.  Breaking either of the last two rules raises nothing: the socket just never gets watched.  `chumicro_runner.testing.validate_service(service)` checks all three and raises `ValueError` naming the member at fault, without calling any of them:

```python
from chumicro_runner.testing import validate_service


def test_my_service_is_a_valid_runner_service():
    validate_service(MySensorService(...))
```

### Choosing the poller

`Runner(poller=...)` accepts any object with `register(obj, eventmask)`, `modify(obj, eventmask)`, `unregister(obj)`, and `ipoll(timeout_ms)`.  The default wraps `select.poll()` and is only built on the first `wait()` with a socket to watch, so a program with no network services never creates one.  Tests pass `FakePoller` from `chumicro_runner.testing`; see [Testing your jobs](#testing-your-jobs).

## What a generator task yields

This section is for writing your own pause helpers, or for driving ChuMicro's generator helpers from a loop that has no `Runner`.

Every `yield` inside a pause helper hands the runner a **wait**: a small object describing what the task is waiting for.  It can carry any of three hooks, all optional:

| Hook | Meaning | Who reads it |
|---|---|---|
| `ready(now_ms) -> bool` | Return `True` once the thing being waited for has happened, without looking at the clock | any driver |
| `next_deadline(now_ms)` | Resume once the clock reaches this tick | any driver, and `Runner.wait()` to bound its sleep |
| `io_socket` + `io_interest(now_ms)` | Resume when this socket is readable or writable | `Runner.wait()`, to sleep on `ipoll` |

A wait never compares times itself.  It publishes its deadline, and whatever drives the task compares that deadline with its own clock, so a `Runner(ticks=...)` built on a different clock measures every pause in its own units.  The rule for resuming is three cases, in order: resume when `ready` answers `True`; otherwise resume once `next_deadline` has passed; otherwise, when the wait has no `ready` at all, resume on any pass.

Socket waits carry neither `ready` nor a deadline, so they take the last case.  Their helpers retry the socket call and pause again when it would block, so resuming early costs one wasted pass and nothing else.

That rule is all it takes to run `chumicro_sockets.generators` from your own loop:

```python
def should_resume(wait, now_ms, ticks):
    ready = getattr(wait, "ready", None)
    if ready is not None and ready(now_ms):
        return True
    next_deadline = getattr(wait, "next_deadline", None)
    deadline_ms = None if next_deadline is None else next_deadline(now_ms)
    if deadline_ms is not None:
        return ticks.ticks_diff(now_ms, deadline_ms) >= 0   # your clock, your units
    return ready is None


wait = generator.send(None)                 # run the task up to its first pause
while True:
    now_ms = ticks.ticks_ms()
    if should_resume(wait, now_ms, ticks):
        try:
            wait = generator.send(now_ms)
        except StopIteration:
            break
```

This loop never sleeps, so on a board it spins where `Runner.wait()` would idle and costs battery, but the task behaves the same.  The library's own tests run a full connect, send, and receive through this loop.

## When a job raises

An exception inside a job, or inside a generator task, does not stop the loop.  The runner catches it, adds one to `runner.handler_errors`, keeps it in `runner.last_handler_error`, and runs the remaining jobs as usual.  It prints nothing, so a job that fails every time fails silently unless you ask to hear about it:

```python
def report_error(task, error):
    print("job failed:", repr(error))

runner = Runner(on_handler_error=report_error)
```

The callback receives the failing job's `TaskHandle` and the exception, so it can also call `task.remove()` to stop a job that keeps failing.  An exception raised inside the callback is caught and counted the same way.  `KeyboardInterrupt` and `SystemExit` are not caught, so Ctrl+C still stops the program.

A job that calls `runner.tick()` itself raises `ReentrantTickError`, which the runner lets through: that is a bug in the program, not a fault in one job.

## Memory notes

- The runner keeps one small `TaskHandle` per job.  A generator task adds the generator and a `GeneratorHandle`.
- `tick()` collects due jobs into a list it reuses from tick to tick, and `wait()` reuses its watch list, so once the loop is running neither allocates.
- `chumicro_runner.generators` and the generator machinery load only when a program first calls `add_generator` or imports them.

## Testing your jobs

`chumicro_runner.testing` provides three helpers for tests that run on your computer:

- `CallRecorder`: a function you register as a job that records the `now_ms` of each call.
- `validate_service`: checks a service against the rules in [The service contract](#the-service-contract).
- `FakePoller`: a stand-in for `select.poll()`, so tests can drive `wait()` with no real sockets.  It records every call the runner makes, and `set_ready(obj, eventmask)` queues a ready socket for the next `ipoll()`.

Pair them with `FakeTicks` from `chumicro_timing.testing`, a clock that only moves when the test says so:

```python
from chumicro_runner import Runner
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

clock = FakeTicks()
recorder = CallRecorder()
runner = Runner(ticks=clock)
runner.add_periodic(recorder, period_ms=100)

runner.tick()
assert len(recorder) == 0     # not due yet

clock.advance(100)
runner.tick()
assert recorder.calls == [100]
```

On a runner built with `FakeTicks`, a `wait()` with no sockets to watch moves the fake clock forward by the time it would have slept, so a test can step through minutes of schedule without sleeping.  The [testing helpers](testing.md) page covers all three, including a `FakePoller` walkthrough.

## Platform notes

The runner is plain Python and runs unchanged on CPython, MicroPython, and CircuitPython.  Two calls inside `wait()` differ by runtime: on the boards it sleeps in `select.poll().ipoll()` and `time.sleep_ms()`, and on CPython, which has neither, it uses `poll()` and `time.sleep()` in their place.

## Examples

The [examples](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples) directory holds complete programs, simplest first.  Every one ends in a `while True:` loop that runs until you stop it.  The ones without a runtime prefix print to the console and run on your computer as well as on a board; the `circuitpython_*` and `micropython_*` ones drive real pins and list their wiring at the top.

| Example | What it shows |
|---|---|
| `periodic_blink.py` | One timed job: a pretend LED that prints on and off every 500 ms |
| `circuitpython_blink.py` | The same blink on a real LED, CircuitPython |
| `micropython_blink.py` | The same blink on a real LED, MicroPython |
| `basic_handler.py` | Plain functions on two timers, plus one that runs on every pass of the loop |
| `sensor_threshold.py` | A service: `check()` reads a pretend sensor, `handle()` prints an alert |
| `circuitpython_button_led.py` | A service that toggles the LED on each button press, CircuitPython |
| `micropython_button_led.py` | A service that toggles the LED on each button press, MicroPython |
| `multi_service.py` | Two services and two timed jobs sharing one loop at different rates |
| `runtime_control.py` | Changing jobs while they run: `set_period()`, `remove()`, and `run_count` |
| `generator_basic.py` | A generator task that blinks a pattern with pauses while another job keeps time |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
