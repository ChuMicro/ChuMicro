# Testing Helpers

`chumicro_serviceable.testing` provides `FakeService` for verifying that service loops and runners call components correctly.

## Usage with ServiceRunner

```python
from chumicro_serviceable import ServiceRunner
from chumicro_serviceable.testing import FakeService
from chumicro_timing.testing import FakeTicks

def test_runner_calls_service_with_shared_time():
    fake = FakeTicks()
    svc = FakeService()
    runner = ServiceRunner(services=[svc], ticks=fake)

    fake.advance(100)
    runner.tick()

    assert svc.ticks == [100]
```

## Inspecting calls

`FakeService.ticks` is a plain list of `now_ms` values passed to `service()`:

```python
svc = FakeService()
svc.service(10)
svc.service(20)
assert svc.ticks == [10, 20]
```

## Usage from other libraries

Libraries that implement the `service(now_ms)` contract can import `FakeService` for testing:

```python
from chumicro_serviceable.testing import FakeService
```

This follows the project convention from [Decision 0010](https://github.com/chumicro/chumicro/blob/main/plans/decisions/0010-library-testability.md): libraries that expose injectable services ship their own test fakes.

## API Reference

::: chumicro_serviceable.testing
    options:
      members:
        - FakeService
