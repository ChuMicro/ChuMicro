# chumicro-runner

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Run several jobs from one `while True:` loop on a microcontroller, with no `time.sleep()` and no `async`.**

A `time.sleep()` blink works until the board needs a second job.  The runner keeps your `while True:` loop and puts a small scheduler inside it.  You register each job once and say how often it runs; `runner.tick()` runs whichever jobs are due, and `runner.wait()` sleeps the board until the next one is.  Every networked library in ChuMicro ([wifi](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), [sockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), [mqtt](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [requests](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [http_server](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [websockets](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets)) registers with the same runner, so your LED keeps blinking through a slow HTTP response or a stalled server.

Works on CircuitPython, MicroPython, and CPython.  Built on [chumicro-timing](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing).

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_runner

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner

# CPython
pip install chumicro-runner
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

## Why not `time.sleep()`?

Here is the first program most board tutorials teach, with a button check added:

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

The board spends nearly all its time inside `time.sleep(0.5)` and looks at the button for an instant twice a second.  A quick tap that starts and ends during the sleep never reaches the program.  A shorter sleep makes the LED blink faster too.  Every job you add brings its own sleep, and each sleep holds up all the others.

## Quick example

The same two jobs on the runner:

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

Each job is a function that does one quick step and returns.  `runner.tick()` reads the clock once, runs every job that is due, and returns that reading in milliseconds as `now_ms`, the same value it passed to each job.  `runner.wait(now_ms)` sleeps until the next job is due.  The button now gets read every 20 ms whatever the LED is doing, and a third job is one more `add_periodic` line.

Keep the `wait()` line.  A loop that calls `tick()` without it never sleeps: it spins the CPU flat out and wastes power.  [`circuitpython_button_led.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/circuitpython_button_led.py) and [`micropython_button_led.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner/examples/micropython_button_led.py) are complete versions of this program for each runtime.

## Three kinds of job

From simplest to most involved.

**Timed jobs.**  `runner.add_periodic(function, period_ms=...)` calls a function on a schedule, as above.  It returns a `TaskHandle`; keep it to change the period later (`handle.set_period(250)`) or stop the job (`handle.remove()`).  `run_count=` limits how many times the job runs, and `start_after_ms=` delays its first run.

**Services.**  A service is an object with two methods the runner calls for you.  `check(now_ms)` answers "is there anything to do?" and `handle(now_ms)` does it.  The runner calls `handle` only on the ticks where `check` returned `True`.  Every network library in ChuMicro is a service, which is why `runner.add(wifi)` is all it takes to keep WiFi connected.

```python
class TemperatureAlarm:
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

**Generator tasks.**  A generator task is a function with pauses in it.  Each `yield from` hands the loop back to the runner, which runs the other jobs and resumes the function on the next line once the pause is over.  It reads like a `time.sleep()` program without stopping everything else:

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

handle = runner.add_generator(heartbeat_blink())
```

The network libraries use the same shape for work that runs in order: connect, send, wait for the reply.  `add_generator` returns a `GeneratorHandle`: `handle.done` turns `True` when the function returns, and `handle.error` holds the exception if it raised.

**Waiting for a task to finish.**  `runner.run_until(...)` is the tick-and-wait loop in one call, for application code that must finish one step before moving on.  It returns once a generator task finishes (re-raising the task's exception if it died) or a function you pass returns something truthy, and returns `False` if `timeout_ms` runs out first:

```python
handle = runner.add_generator(fetch_settings())
runner.run_until(handle)   # tick and wait until fetch_settings() returns

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

This library's examples write the loop out instead, so you can see every step.

## When a job raises

An exception inside a job does not stop the loop.  The runner catches it, adds one to `runner.handler_errors`, keeps the exception in `runner.last_handler_error`, and runs the other jobs as usual.  It prints nothing, so pass a callback to hear about it:

```python
def report_error(task, error):
    print("job failed:", repr(error))

runner = Runner(on_handler_error=report_error)
```

The callback receives the failing job's `TaskHandle`, so it can also call `task.remove()` to stop that job.  An exception raised inside the callback is caught and counted the same way.

## What's included

### Core

| Symbol | Description |
|---|---|
| `Runner(ticks=None, poller=None, on_handler_error=None)` | The scheduler.  `on_handler_error(task, exception)` is called when a job raises.  `ticks` and `poller` swap in a different clock and socket poller, mainly for tests |
| `Runner.add_periodic(handler, period_ms, start_after_ms=None, run_count=None, preserve_phase=False)` | Register a function to call every `period_ms`; returns a `TaskHandle` |
| `Runner.add(task, handler=None, period_ms=None, start_after_ms=None, run_count=None, preserve_phase=False)` | Register a service (an object with `check` and `handle`) or, with `handler=`, a plain function.  With no `period_ms`, it runs on every tick; returns a `TaskHandle` |
| `Runner.add_generator(generator)` | Register a generator task; returns a `GeneratorHandle`.  See [Generator tasks](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks) in the guide |
| `Runner.tick()` | Read the clock once, run every job that is due, and return that time as `now_ms`.  Raises `ReentrantTickError` if a job calls `tick()` |
| `Runner.wait(now_ms)` | Sleep until the next job is due or a registered socket is ready.  See [How `wait()` decides how long to sleep](https://chumicro.com/ChuMicro/runner/stable/guide/#how-wait-decides-how-long-to-sleep) in the guide |
| `Runner.run_until(predicate, timeout_ms=None)` | Tick and wait until a `GeneratorHandle` finishes or a zero-argument function returns truthy; returns `False` on timeout |
| `Runner.handler_errors` / `Runner.last_handler_error` | Count of exceptions caught from jobs, and the most recent one |
| `TaskHandle.set_period(period_ms, now_ms=None)` | Change the period, or pass `None` to run on every tick.  Pass the tick's `now_ms` to count the new period from that tick |
| `TaskHandle.remove()` | Take the job off the runner |
| `TaskHandle.period_ms` / `.run_count` / `.active` | Current period, runs left (`None` for unlimited), and whether the job is still registered.  Change the period with `set_period()`, not by assignment |
| `GeneratorHandle.done` / `.error` | `True` once the generator returns, raises, or is cancelled; the exception it raised, or `None` |
| `GeneratorHandle.cancel()` | Stop the generator early; any `finally` block inside it runs |
| `IO_READ` / `IO_WRITE` | Bits a network service returns from `io_interest(now_ms)` to ask `wait()` to wake when its socket is readable or writable |
| `ReentrantTickError` | Raised when `tick()` runs while another `tick()` is in progress |

### Generator helpers

`chumicro_runner.generators` holds `sleep_until`.  Import it explicitly; a program with no generator tasks never loads it.  The other pause helpers a generator task uses live in `chumicro_timing` and `chumicro_sockets`:

| Symbol | Description |
|---|---|
| `sleep_until(until_ms)` | Pause until the clock reaches `until_ms`; pair with `ticks_add(ticks_ms(), delay_ms)` from `chumicro_timing` |
| `Signal` / `wait_for(signal, deadline_ms=None)` (`chumicro_timing.waits`) | Pause until a callback calls `signal.set(value)`, then return the value; raises `OSError(ETIMEDOUT)` past the optional deadline |
| `connect(connector)` (`chumicro_sockets.generators`) | Open a connection and return the socket: `sock = yield from connect(connector(host, port))` |
| `send_all(sock, data)` (`chumicro_sockets.generators`) | Send every byte of `data`, pausing whenever the socket is full |
| `recv_until(sock, separator, max_bytes=...)` (`chumicro_sockets.generators`) | Read until `separator` arrives, refusing to buffer more than `max_bytes` |
| `ReadWait(sock)` / `WriteWait(sock)` (`chumicro_sockets.waits`) | Pause until `sock` is readable or writable, for writing your own socket helpers |

A `Signal` connects a callback to a generator task: hand `signal.set` to a service as its callback, then `value = yield from wait_for(signal)` inside the task:

```python
link_up = Signal()
wifi.on_state_change(lambda old, new: link_up.set(new))
state = yield from wait_for(link_up)
```

### Testing

| Symbol | Description |
|---|---|
| `CallRecorder()` | A function to register as a job that records the `now_ms` of every call in `.calls` |
| `validate_service(service)` | Check that an object has the methods `Runner.add` and `wait()` expect; raises `ValueError` naming the problem |
| `FakePoller()` | Stand-in for the socket poller so tests can drive `wait()` without real sockets: `Runner(poller=FakePoller())` |

## Where this fits

Depends on [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the clock.  Every networked library in ChuMicro ([`wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), [`sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets), [`requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`http_server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server), [`mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets)) registers here, so the runner sits at the center of any program that runs more than one of them.

## Platform support

Plain Python that runs unchanged on CPython, MicroPython, and CircuitPython.  Each registered job costs one small object, and once the loop is running `tick()` and `wait()` allocate nothing.

## Examples

From simplest to most involved.  The ones without a runtime prefix print to the console and run on your computer as well as on a board.

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

The [full user guide](https://chumicro.com/ChuMicro/runner/stable/guide/) walks through the same steps in more depth: timed jobs, services, generator tasks, how `wait()` sleeps, and testing your own jobs.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/runner/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/runner/experimental/)**

## Find this library

- **PyPI:** [chumicro-runner](https://pypi.org/project/chumicro-runner/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_runner) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_runner)
- **Source:** [libraries/runner](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
