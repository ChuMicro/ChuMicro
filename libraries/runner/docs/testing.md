# Testing Helpers

`chumicro_runner.testing` holds three helpers for testing code a `Runner` drives.  `CallRecorder` stands in for a job and records each call the runner makes to it.  `FakePoller` stands in for `select.poll()`, the socket watcher `Runner.wait()` sleeps on.  `validate_service` checks that a service object has the methods `Runner.add` expects.  `pip install chumicro-runner pytest` installs everything the tests on this page import, `chumicro-timing` included.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_blink_schedule.py` and run `pytest test_blink_schedule.py`:

```python
from chumicro_runner import Runner
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks


def test_a_periodic_job_runs_once_per_period():
    clock = FakeTicks()
    runner = Runner(ticks=clock)
    blink = CallRecorder()
    runner.add_periodic(blink, period_ms=100)

    runner.tick()
    assert blink.calls == []

    clock.advance(100)
    runner.tick()
    assert blink.calls == [100]
```

`Runner(ticks=clock)` reads the time from `FakeTicks`, so the job runs only when the test moves the clock.

## `CallRecorder`

`CallRecorder` is a callable, so it registers anywhere a job function does.

| Call or attribute | What it does |
|---|---|
| `calls` | The `now_ms` of each call, in order. |
| `len(recorder)` | The number of calls. |
| `clear()` | Forgets the calls so far, between phases of a test. |

A job added with no period runs on every tick:

```python
from chumicro_runner import Runner
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks


def test_a_job_without_a_period_runs_every_tick():
    runner = Runner(ticks=FakeTicks())
    recorder = CallRecorder()
    runner.add(handler=recorder)

    runner.tick()
    runner.tick()
    assert len(recorder) == 2

    recorder.clear()
    assert len(recorder) == 0
```

## `FakePoller`

`Runner.wait()` sleeps until a socket is ready or the next job is due.  It watches the sockets through a poller.  CPython's `select.poll` needs real sockets, so a test passes `poller=FakePoller()` and checks what the runner asked it to watch.

| Call or attribute | What it does |
|---|---|
| `register_calls`, `modify_calls`, `unregister_calls` | Each call the runner made, as `(socket, eventmask)` pairs, or just the socket for `unregister`. |
| `ipoll_calls` | The timeout in milliseconds of each `ipoll()` call, which is how long the runner meant to sleep. |
| `registered` | The sockets watched right now, as `{id(socket): (socket, eventmask)}`. |
| `set_ready(socket, eventmask)` | Queues a ready socket for the next `ipoll()` to return. |

```python
import select

from chumicro_runner import IO_READ, Runner
from chumicro_runner.testing import FakePoller
from chumicro_timing.testing import FakeTicks


class ReadService:
    def __init__(self, sock):
        self.io_socket = sock

    def io_interest(self, now_ms):
        return IO_READ

    def check(self, now_ms):
        return False

    def handle(self, now_ms):
        pass


def test_wait_watches_the_service_socket():
    poller = FakePoller()
    runner = Runner(ticks=FakeTicks(), poller=poller)
    sock = object()
    runner.add(ReadService(sock), period_ms=100)

    runner.wait(0)

    assert (sock, select.POLLIN) in poller.register_calls
    assert poller.ipoll_calls == [100]
```

The runner registered the socket for reading and slept until the service's next period, 100 ms away.

## `validate_service`

`validate_service(service)` reads which runner methods and attributes a service defines, and raises `ValueError` naming the member at fault when they do not fit together.  It calls none of them, so it is safe on a service that would talk to hardware.

It enforces the rules `Runner` relies on:

- `check` and `handle` are both required.
- `io_socket` and `io_interest` come as a pair.
- `io_error` needs an `io_socket` to report errors on.
- `next_deadline` is optional and stands alone.

```python
from chumicro_runner.testing import validate_service


class Blinker:
    def check(self, now_ms):
        return True

    def handle(self, now_ms):
        pass


class HalfWired:
    io_socket = None

    def check(self, now_ms):
        return False

    def handle(self, now_ms):
        pass


def test_validate_service_accepts_and_rejects():
    validate_service(Blinker())

    try:
        validate_service(HalfWired())
        raise AssertionError("expected ValueError")
    except ValueError as error:
        assert "io_interest" in str(error)
```

`HalfWired` has an `io_socket` and no `io_interest`, so the runner would never poll its socket.

## API reference

::: chumicro_runner.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
