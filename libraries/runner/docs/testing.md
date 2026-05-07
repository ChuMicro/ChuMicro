# Testing Helpers

`chumicro_runner.testing` provides `CallRecorder` for verifying that handlers fire at the right times in host-side tests — a simple callable that records invocations.

## Usage as a handler

Pass a `CallRecorder` as the handler to `Runner.add()` or `add_periodic()`:

```python
from chumicro_runner import Runner
from chumicro_runner.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
recorder = CallRecorder()
runner = Runner(ticks=fake)
runner.add_periodic(recorder, period_ms=100)

# Not due yet — no calls.
runner.tick()
assert len(recorder) == 0

# Advance past the period.
fake.advance(100)
runner.tick()
assert recorder.calls == [100]
```

## Inspecting calls

`CallRecorder.calls` is a plain list of `now_ms` values from each invocation:

```python
assert recorder.calls[0] == 100
assert len(recorder) == 1
```

## Clearing between tests

Call `clear()` to reset the recorder between test phases:

```python
recorder.clear()
assert len(recorder) == 0
```

## Usage with gate-based services

`CallRecorder` works equally well as a handler for gate-based registrations:

```python
recorder = CallRecorder()
runner.add(
    lambda now_ms: True,  # always fire
    handler=recorder,
)
runner.tick()
assert len(recorder) == 1
```

## Usage from other libraries

Libraries that use the runner pattern can import `CallRecorder` directly:

```python
# In another library's test file
from chumicro_runner.testing import CallRecorder
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_runner.testing
    options:
      members:
        - CallRecorder

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · [PyPI](https://pypi.org/project/chumicro-runner/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
