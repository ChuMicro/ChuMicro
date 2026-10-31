# Testing Helpers

`chumicro_runner.testing` holds three helpers for tests that run on your computer: `CallRecorder` records each call the runner makes to a job, `validate_service` checks that an object has the methods `Runner.add` expects, and `FakePoller` stands in for `select.poll()` so tests can drive `Runner.wait()` without real sockets.  ChuMicro's deploy tools and bundles leave this module off the board, so it costs a device no flash.

The `CallRecorder` and `FakePoller` examples build the runner on `FakeTicks` from `chumicro_timing.testing`, a clock that moves only when the test calls `advance()`.

## `CallRecorder`

`CallRecorder` is a callable, so it registers anywhere a job function does:

```python
from chumicro_runner import Runner
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
recorder = CallRecorder()
runner = Runner(ticks=fake)
runner.add_periodic(recorder, period_ms=100)

# Not due yet, so nothing fires.
runner.tick()
assert len(recorder) == 0

# Advance past the period.
fake.advance(100)
runner.tick()
assert recorder.calls == [100]
```

`recorder.calls` is a plain list of the `now_ms` value from each invocation, and `clear()` resets it between phases of a test:

```python
assert recorder.calls[0] == 100
assert len(recorder) == 1

recorder.clear()
assert len(recorder) == 0
```

A job registered without a period runs on every tick:

```python
recorder = CallRecorder()
runner.add(handler=recorder)
runner.tick()
assert len(recorder) == 1
```

## `validate_service`

`validate_service(service)` looks at which of the runner's methods and attributes your service defines, and raises `ValueError` naming the one at fault when they do not fit together.  It only looks: it never calls `check`, `handle`, or any other method, so it is safe to run against a service that would talk to hardware.

```python
from chumicro_runner.testing import validate_service

class Blinker:
    def check(self, now_ms):
        return True

    def handle(self, now_ms):
        pass

validate_service(Blinker())        # passes, nothing raised
```

The rules it enforces are the ones `Runner` dispatch relies on: `check` and `handle` are both required; `io_socket` and `io_interest` come as a pair; `io_error` needs an `io_socket` to report errors on.  `next_deadline` is optional and stands alone.

```python
class HalfWired:
    io_socket = None                # no io_interest to go with it

    def check(self, now_ms):
        return False

    def handle(self, now_ms):
        pass

validate_service(HalfWired())
# ValueError: a service with io_socket must also define io_interest;
# the runner polls the socket only through io_interest
```

## `FakePoller`

`Runner.wait()` watches network services' sockets through a poller object.  CPython's real `select.poll` needs live file descriptors, which in-memory fake sockets do not have, so pass `poller=FakePoller()` and assert on what the runner asked it to watch.  `register_calls`, `modify_calls`, `unregister_calls`, and `ipoll_calls` record every call; `set_ready(obj, eventmask)` queues a pair for the next `ipoll()` return.

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

poller = FakePoller()
runner = Runner(ticks=FakeTicks(), poller=poller)
sock = object()
runner.add(ReadService(sock), period_ms=100)

runner.wait(0)

assert (sock, select.POLLIN) in poller.register_calls
assert poller.ipoll_calls == [100]      # idled until the next period
```

## Using these fakes in your own tests

Your test suite imports them straight from the installed package, the same way this library's own tests do:

```python
from chumicro_runner.testing import CallRecorder, FakePoller, validate_service
```

ChuMicro libraries that take a clock, socket, or other dependency as an argument ship fakes for it in a `testing` module like this one.

## API Reference

::: chumicro_runner.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
