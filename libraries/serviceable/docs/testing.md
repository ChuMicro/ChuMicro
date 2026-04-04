# Testing Helpers

`chumicro_serviceable.testing` provides `CallRecorder` for verifying that handlers fire at the right times in host-side tests — a simple callable that records invocations.

## Usage as a handler

Pass a `CallRecorder` as the handler to `ServiceRunner.add()` or `add_periodic()`:

```python
from chumicro_serviceable import ServiceRunner
from chumicro_serviceable.testing import CallRecorder
from chumicro_timing.testing import FakeTicks

fake = FakeTicks()
recorder = CallRecorder()
runner = ServiceRunner(ticks=fake)
runner.add_periodic(recorder, period_ms=100)

# Not due yet — no calls.
runner.service_once()
assert len(recorder) == 0

# Advance past the period.
fake.advance(100)
runner.service_once()
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
runner.service_once()
assert len(recorder) == 1
```

## Usage from other libraries

Libraries that use the serviceable pattern can import `CallRecorder` directly:

```python
# In another library's test file
from chumicro_serviceable.testing import CallRecorder
```

This follows the project convention from [Decision 0010](https://github.com/chumicro/chumicro/blob/main/plans/decisions/0010-library-testability.md): libraries that expose injectable services ship their own test fakes.

## API Reference

::: chumicro_serviceable.testing
    options:
      members:
        - CallRecorder
